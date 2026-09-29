import asyncio
import io
import os
import secrets
import zipfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from docx import Document
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .demo import seed_demo
from .interview import InterviewAssistant, add_resume
from .interview_routes import interview_router
from .matching import extract_profile
from .models import Decision, Profile, Review, Source
from .service import SearchService
from .store import Store, fingerprint

ROOT = Path(__file__).resolve().parent.parent
Mode = Literal["live", "demo"]


class Toggle(BaseModel):
    enabled: bool


def create_app(data_dir=None, schedule=True):
    data_dir = Path(data_dir or os.environ.get("SCOUT_DATA_DIR", ROOT / "data"))
    live, demo = Store(data_dir / "scout.sqlite"), Store(data_dir / "demo.sqlite")
    seed_demo(demo)
    live.recover_runs()
    token = os.environ.get("SCOUT_TOKEN", "")
    discovery_key = os.environ.get("TAVILY_API_KEY", "")
    service = SearchService(live, discovery_key)
    interviewer = InterviewAssistant(ROOT)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(service.scheduler()) if schedule else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Job Scout", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    app.state.live, app.state.demo, app.state.service = live, demo, service
    app.state.interviewer = interviewer
    app.include_router(interview_router(live, demo, interviewer))

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if token and not secrets.compare_digest(
                request.headers.get("authorization", ""), f"Bearer {token}"
            ):
                return JSONResponse(
                    {"detail": "Enter the configured access token"}, status_code=401
                )
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse(
                    {"detail": "Cross-origin requests are disabled"}, status_code=403
                )
            if (
                request.method not in {"GET", "HEAD"}
                and request.headers.get("x-scout-client") != "job-scout"
            ):
                return JSONResponse({"detail": "Missing local client header"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def store(mode):
        return demo if mode == "demo" else live

    @app.get("/api/state")
    def state(mode: Mode = "live"):
        db = store(mode)
        profile = db.profile()
        return {
            "profile": profile.model_dump(),
            "profile_version": fingerprint(profile.model_dump()),
            "sources": db.sources(),
            "jobs": db.jobs(),
            "runs": db.runs(),
            "mode": mode,
            "daily": db.setting("daily", False),
            "next_run": db.setting("next_run"),
            "refreshing": service.lock.locked() if mode == "live" else False,
            "discovery_available": bool(discovery_key),
            "matching": "Evidence-based rules; Brigade reviews appear when connected",
        }

    @app.put("/api/profile")
    def save_profile(profile: Profile, mode: Mode = "live"):
        store(mode).save_profile(profile)
        return {"ok": True}

    @app.post("/api/resume")
    async def resume(
        file: UploadFile = File(...),
        remember: bool = False,
        revision: int | None = None,
        mode: Mode = "live",
    ):
        content = await file.read(5 * 1024 * 1024 + 1)
        await file.close()
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(413, "Resume must be smaller than 5 MB")
        suffix = Path(file.filename or "").suffix.lower()
        try:
            if suffix == ".pdf":
                reader = PdfReader(io.BytesIO(content))
                if len(reader.pages) > 30:
                    raise HTTPException(422, "Use a resume with at most 30 pages")
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
            elif suffix == ".docx":
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    if sum(item.file_size for item in archive.infolist()) > 20 * 1024 * 1024:
                        raise HTTPException(422, "Expanded document is too large")
                doc = Document(io.BytesIO(content))
                text = "\n".join(
                    [p.text for p in doc.paragraphs]
                    + [cell.text for t in doc.tables for r in t.rows for cell in r.cells]
                )
            elif suffix in {".txt", ".md"}:
                text = content.decode("utf-8")
            else:
                raise HTTPException(422, "Upload a PDF, DOCX, or UTF-8 text file")
        except (PdfReadError, zipfile.BadZipFile, UnicodeDecodeError, ValueError, KeyError) as exc:
            raise HTTPException(422, "Could not read this document. Try a text export.") from exc
        if len(text.strip()) < 30:
            raise HTTPException(
                422, "No usable text found. Scanned PDFs need OCR; paste or upload a text version."
            )
        if remember:
            if revision is None:
                raise HTTPException(422, "A conversation version is required")
            try:
                add_resume(store(mode), text, revision)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        return {
            "profile": extract_profile(text[:100000]).model_dump(),
            "message": (
                "CV text added to your local conversation. Review the suggested roles and skills. "
                "Nothing was sent to a model."
            )
            if remember
            else (
                "Review these suggested roles and skills before saving. "
                "The uploaded file was not stored or sent to a model."
            ),
        }

    @app.post("/api/sources")
    def add_source(source: Source, mode: Mode = "live"):
        if len(store(mode).sources()) >= 40:
            raise HTTPException(422, "This prototype supports up to 40 employer boards")
        store(mode).add_source(source)
        return {"ok": True}

    @app.patch("/api/sources/{source_id}")
    def toggle_source(source_id: int, value: Toggle, mode: Mode = "live"):
        if not store(mode).toggle_source(source_id, value.enabled):
            raise HTTPException(404, "Source not found")
        return {"ok": True}

    @app.post("/api/refresh")
    async def refresh(mode: Mode = "live", discover: bool = False):
        if mode == "demo":
            return {
                "status": "demo",
                "found": len(demo.jobs()),
                "added": 0,
                "changed": 0,
                "errors": [],
            }
        if discover and not discovery_key:
            raise HTTPException(
                422, "Employer discovery needs TAVILY_API_KEY or the Brigade extension"
            )
        if service.lock.locked():
            raise HTTPException(409, "A refresh is already running")
        return await service.refresh(discover_new=discover)

    @app.patch("/api/jobs/{jid}")
    def decide(jid: str, decision: Decision, mode: Mode = "live"):
        if not store(mode).decision(jid, decision.status, decision.reason):
            raise HTTPException(404, "Job not found")
        return {"ok": True}

    @app.post("/api/jobs/{jid}/review")
    def review(jid: str, value: Review, mode: Mode = "live"):
        db = store(mode)
        job = db.job(jid)
        if not job:
            raise HTTPException(404, "Job not found")
        if (
            value.profile_version != fingerprint(db.profile().model_dump())
            or value.job_version != job["version"]
        ):
            raise HTTPException(409, "Profile or listing changed; read it again before reviewing")
        evidence_text = " ".join(
            f"{job['title']} {job['location']} {job['description']} {job['salary']}".split()
        ).lower()
        if any(" ".join(e.quote.split()).lower() not in evidence_text for e in value.evidence):
            raise HTTPException(422, "Every evidence quote must appear in the listing")
        db.review(jid, value.model_dump())
        return {"ok": True}

    @app.put("/api/schedule")
    def schedule_refresh(value: Toggle, mode: Mode = "live"):
        if mode == "demo":
            raise HTTPException(422, "Daily updates are available in your live workspace")
        live.set_setting("daily", value.enabled)
        return {"ok": True}

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app
