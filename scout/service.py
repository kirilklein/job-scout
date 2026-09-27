import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx

from .feeds import discover, fetch_source
from .models import Source

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, store, discovery_key="", fetcher=fetch_source):
        self.store, self.discovery_key, self.fetcher = store, discovery_key, fetcher
        self.lock = asyncio.Lock()

    async def refresh(self, discover_new=False):
        if self.lock.locked():
            raise RuntimeError("A refresh is already running")
        async with self.lock:
            run_id = self.store.begin_run()
            next_run = (datetime.now(UTC) + timedelta(days=1)).isoformat()
            self.store.set_setting("next_run", next_run)
            result = {"added": 0, "changed": 0, "found": 0, "errors": [], "sources": 0}
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                    if discover_new and self.discovery_key:
                        try:
                            for source in await discover(
                                self.store.profile(), self.discovery_key, client
                            ):
                                if len(self.store.sources()) < 40:
                                    self.store.add_source(source)
                        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                            result["errors"].append(
                                f"Employer discovery failed: {type(exc).__name__}"
                            )
                    semaphore = asyncio.Semaphore(4)

                    async def collect(row):
                        async with semaphore:
                            try:
                                jobs = await self.fetcher(Source.model_validate(row), client)
                                counts = self.store.ingest(row["id"], jobs)
                                for key in ["added", "changed", "found"]:
                                    result[key] += counts[key]
                                result["sources"] += 1
                            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                                error = f"{row['company']}: {type(exc).__name__}"
                                if isinstance(exc, httpx.HTTPStatusError):
                                    error += f" (HTTP {exc.response.status_code})"
                                self.store.source_error(row["id"], error)
                                result["errors"].append(error)

                    rows = [row for row in self.store.sources() if row["enabled"]]
                    if not rows:
                        result["errors"].append(
                            "No active sources. Add an employer board in Sources."
                        )
                    tasks = [asyncio.create_task(collect(row)) for row in rows]
                    try:
                        await asyncio.gather(*tasks)
                    finally:
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                status = (
                    "partial"
                    if result["errors"] and result["sources"]
                    else "failed"
                    if result["errors"]
                    else "complete"
                )
                self.store.end_run(run_id, status, result)
                return {**result, "status": status}
            except BaseException:
                self.store.end_run(
                    run_id, "failed", {"errors": ["Refresh interrupted by an unexpected failure"]}
                )
                raise

    async def refresh_if_due(self):
        if not self.store.setting("daily", False) or self.lock.locked():
            return
        due = self.store.setting("next_run")
        if due and datetime.fromisoformat(due) > datetime.now(UTC):
            return
        return await self.refresh(discover_new=bool(self.discovery_key))

    async def scheduler(self):
        while True:
            await asyncio.sleep(30)
            try:
                await self.refresh_if_due()
            except Exception:
                logger.exception("Scheduled refresh failed; see run history")
