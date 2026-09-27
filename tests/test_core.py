import asyncio
import io

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient

from scout.app import create_app
from scout.feeds import normalize, source_from_url
from scout.matching import contains, extract_profile, match
from scout.models import Profile, Source
from scout.service import SearchService
from scout.store import Store, fingerprint


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.sqlite")


@pytest.fixture
def job():
    return {
        "external_id": "j1",
        "title": "Machine Learning Engineer",
        "company": "Example",
        "description": "Build machine learning tools with Python and SQL for healthcare.",
        "location": "Copenhagen, Denmark",
        "workplace": "hybrid",
        "salary": "",
        "url": "https://example.com/job",
        "published": None,
    }


def add_job(store, job):
    store.add_source(Source(provider="greenhouse", board="example", company="Example"))
    source_id = store.sources()[0]["id"]
    store.ingest(source_id, [job])
    return source_id, store.jobs()[0]["id"]


def test_resume_extracts_only_supported_skills():
    profile = extract_profile(
        "I am a Machine Learning Engineer with Python, PyTorch and SQL experience."
    )
    assert profile.skills == ["Python", "SQL", "PyTorch", "machine learning"]
    assert profile.roles == ["machine learning engineer"]
    assert profile.locations == []
    assert not contains("React engineer", "R")
    assert contains("Uses C++ daily", "C++")


def test_matching_separates_constraints_unknowns_and_evidence(job):
    profile = Profile(
        roles=["ML engineer"],
        skills=["Python", "SQL"],
        locations=["Copenhagen"],
        interests=["healthcare"],
    )
    result = match(job, profile)
    assert result["eligible"]
    assert result["skills"] == ["Python", "SQL"]
    assert "Salary is not listed" in result["gaps"]
    assert result["score"] > 50
    profile.remote = "remote"
    assert not match(job, profile)["eligible"]
    job["workplace"] = "unknown"
    assert match(job, profile)["eligible"]
    assert "Work arrangement is not specified" in match(job, profile)["gaps"]


def test_remote_does_not_imply_country_eligibility(job):
    job.update(location="Remote", workplace="remote")
    result = match(job, Profile(locations=["Denmark"], remote="remote"))
    assert result["eligible"]
    assert any("work-authorization" in gap for gap in result["gaps"])


def test_exclusions_are_whole_terms(job):
    assert not match(job, Profile(excluded=["healthcare"]))["eligible"]
    assert match(job, Profile(excluded=["care"]))["eligible"]


def test_refresh_dedupes_preserves_decisions_and_reopens(store, job):
    source_id, jid = add_job(store, job)
    store.decision(jid, "saved", "Interesting")
    assert store.ingest(source_id, [job])["added"] == 0
    assert len(store.jobs()) == 1
    first_seen = store.jobs()[0]["first_seen"]
    store.ingest(source_id, [])
    assert not store.job(jid)["active"]
    job["title"] = "Senior ML Engineer"
    result = store.ingest(source_id, [job])
    assert result["changed"] == 1
    updated = store.job(jid)
    assert updated["status"] == "saved" and updated["reason"] == "Interesting"
    assert updated["active"] and updated["first_seen"] == first_seen


def test_review_invalidates_on_listing_or_profile_change(store, job):
    source_id, jid = add_job(store, job)
    store.review(
        jid, {"profile_version": fingerprint(store.profile().model_dump()), "summary": "A review"}
    )
    assert store.job(jid)["review"]
    store.save_profile(Profile(skills=["SQL"]))
    assert store.job(jid)["review"] is None
    store.review(
        jid, {"profile_version": fingerprint(store.profile().model_dump()), "summary": "Updated"}
    )
    job["description"] += " New requirement."
    store.ingest(source_id, [job])
    assert store.job(jid)["review"] is None


def test_failed_feed_preserves_jobs_and_records_partial_run(store, job):
    source_id, jid = add_job(store, job)
    store.add_source(Source(provider="lever", board="other", company="Other"))

    async def fetcher(source, client):
        if source.board == "example":
            raise httpx.ReadTimeout("Timeout")
        return []

    result = asyncio.run(SearchService(store, fetcher=fetcher).refresh())
    assert result["status"] == "partial"
    assert store.job(jid)["active"]
    assert store.sources()[0]["error"]
    assert store.runs()[0]["status"] == "partial"
    assert store.setting("next_run")


def test_unexpected_feed_error_is_recorded_and_surfaces(store, job):
    add_job(store, job)

    async def fetcher(source, client):
        raise RuntimeError("implementation bug")

    with pytest.raises(RuntimeError, match="implementation bug"):
        asyncio.run(SearchService(store, fetcher=fetcher).refresh())
    assert store.runs()[0]["status"] == "failed"


def test_feed_normalizers_and_discovery():
    gh = Source(provider="greenhouse", board="example", company="Example")
    result = normalize(
        gh,
        {
            "jobs": [
                {
                    "id": 2,
                    "title": "Engineer",
                    "location": {"name": "Remote"},
                    "absolute_url": "https://example.com/jobs/2",
                    "content": "<p>Python &amp; SQL</p>",
                }
            ]
        },
    )
    assert result[0]["description"] == "Python & SQL"
    assert result[0]["workplace"] == "remote"
    ashby = Source(provider="ashby", board="example", company="Example")
    assert normalize(ashby, {"jobs": [{"isListed": False}]}) == []
    lever = Source(provider="lever", board="example", company="Example")
    result = normalize(
        lever,
        [
            {
                "id": "a",
                "text": "Engineer",
                "hostedUrl": "https://jobs.lever.co/example/a",
                "workplaceType": "hybrid",
                "salaryRange": {"min": 1, "max": 2, "currency": "USD", "interval": "year"},
                "lists": [{"text": "Requirements", "content": "<li>Python</li>"}],
            }
        ],
    )
    assert result[0]["workplace"] == "hybrid"
    assert "Python" in result[0]["description"]
    assert "USD" in result[0]["salary"]
    assert source_from_url("https://jobs.ashbyhq.com/openai/abc").board == "openai"
    assert source_from_url("https://jobs.ashbyhq.com.evil.example/openai") is None
    assert source_from_url("https://jobs.ashbyhq.com/../admin") is None


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, schedule=False)
    with TestClient(app, headers={"X-Scout-Client": "job-scout"}) as client:
        yield client


def test_api_profile_persistence_and_demo_isolation(client):
    assert client.get("/api/state").json()["jobs"] == []
    assert len(client.get("/api/state?mode=demo").json()["jobs"]) == 6
    assert (
        client.put(
            "/api/profile", json={"roles": ["Data scientist"], "skills": ["SQL"]}
        ).status_code
        == 200
    )
    assert client.get("/api/state").json()["profile"]["skills"] == ["SQL"]
    assert client.get("/api/state?mode=demo").json()["profile"]["name"] == "Alex"
    assert client.post("/api/refresh?mode=demo").json()["status"] == "demo"
    assert client.put("/api/schedule?mode=demo", json={"enabled": True}).status_code == 422


def test_api_rejects_invented_and_stale_evidence(client, job):
    store = client.app.state.live
    _, jid = add_job(store, job)
    review = {
        "fit": "possible",
        "summary": "Python overlaps with the role",
        "evidence": [{"claim": "Uses Python", "quote": "tools with Python and SQL"}],
        "gaps": ["Seniority unknown"],
        "profile_version": fingerprint(store.profile().model_dump()),
        "job_version": store.job(jid)["version"],
    }
    assert client.post(f"/api/jobs/{jid}/review", json=review).status_code == 200
    review["evidence"][0]["quote"] = "Guaranteed visa sponsorship and high salary"
    assert client.post(f"/api/jobs/{jid}/review", json=review).status_code == 422
    review["profile_version"] = "stale"
    assert client.post(f"/api/jobs/{jid}/review", json=review).status_code == 409


def test_api_upload_text_docx_and_errors(client):
    text = b"Experienced machine learning engineer working with Python, SQL and PyTorch."
    response = client.post("/api/resume", files={"file": ("resume.txt", text, "text/plain")})
    assert response.status_code == 200
    assert "Python" in response.json()["profile"]["skills"]
    assert client.get("/api/state").json()["profile"]["skills"] == []
    document, buf = Document(), io.BytesIO()
    document.add_paragraph(text.decode())
    document.save(buf)
    assert (
        client.post("/api/resume", files={"file": ("resume.docx", buf.getvalue())}).status_code
        == 200
    )
    assert client.post("/api/resume", files={"file": ("bad.pdf", b"not a pdf")}).status_code == 422
    assert (
        client.post(
            "/api/resume", files={"file": ("large.txt", b"x" * (5 * 1024 * 1024 + 1))}
        ).status_code
        == 413
    )


def test_local_request_guards(client):
    assert (
        client.put("/api/profile", json={}, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.get("/api/state", headers={"Host": "evil.example"}).status_code == 400
    assert (
        client.post(
            "/api/sources", json={"provider": "ashby", "company": "x", "board": "../../etc"}
        ).status_code
        == 422
    )
    assert client.get("/").headers["content-security-policy"]


def test_optional_token(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_TOKEN", "test-secret")
    with TestClient(create_app(tmp_path, schedule=False)) as client:
        assert client.get("/api/state").status_code == 401
        assert (
            client.get("/api/state", headers={"Authorization": "Bearer test-secret"}).status_code
            == 200
        )


def test_null_ashby_arrangement_and_encoded_greenhouse_html():
    source = Source(provider="ashby", board="example", company="Example")
    jobs = normalize(
        source,
        {
            "jobs": [
                {
                    "title": "Engineer",
                    "jobUrl": "https://example.com/a",
                    "workplaceType": None,
                    "descriptionPlain": None,
                    "location": None,
                }
            ]
        },
    )
    assert jobs[0]["workplace"] == "unknown"
    assert jobs[0]["location"] == "Not specified"
    source = Source(provider="greenhouse", board="example", company="Example")
    jobs = normalize(
        source,
        {
            "jobs": [
                {
                    "id": 1,
                    "title": "Engineer",
                    "absolute_url": "https://example.com/a",
                    "location": None,
                    "content": "&lt;p&gt;Python &amp;amp; SQL&lt;/p&gt;",
                }
            ]
        },
    )
    assert jobs[0]["description"] == "Python & SQL"


def test_daily_schedule_survives_restart_and_does_not_double_run(store, job):
    add_job(store, job)
    calls = []

    async def fetcher(source, client):
        calls.append(source.board)
        return [job]

    async def run():
        service = SearchService(store, fetcher=fetcher)
        assert await service.refresh_if_due() is None
        assert calls == []
        store.set_setting("daily", True)
        assert (await service.refresh_if_due())["status"] == "complete"
        restarted = SearchService(Store(store.path), fetcher=fetcher)
        assert await restarted.refresh_if_due() is None
        assert calls == ["example"]
        store.set_setting("next_run", "2000-01-01T00:00:00+00:00")
        assert (await restarted.refresh_if_due())["status"] == "complete"
        assert len(calls) == 2

    asyncio.run(run())


def test_duplicate_concurrent_refresh_is_rejected(store, job):
    add_job(store, job)

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def fetcher(source, client):
            entered.set()
            await release.wait()
            return [job]

        service = SearchService(store, fetcher=fetcher)
        pending = asyncio.create_task(service.refresh())
        await entered.wait()
        with pytest.raises(RuntimeError, match="already running"):
            await service.refresh()
        release.set()
        await pending
        assert len(store.runs()) == 1

    asyncio.run(run())
