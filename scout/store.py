import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .matching import match
from .models import Profile, Source


def now() -> str:
    return datetime.now(UTC).isoformat()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:20]


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY, provider TEXT NOT NULL, board TEXT NOT NULL,
                    company TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    checked TEXT, error TEXT, UNIQUE(provider, board));
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
                    data TEXT NOT NULL, version TEXT NOT NULL, first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'new', reason TEXT NOT NULL DEFAULT '',
                    review TEXT);
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY, started TEXT NOT NULL, finished TEXT,
                    status TEXT NOT NULL, result TEXT);
            """)
        path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))

    def profile(self):
        return Profile.model_validate(self.setting("profile", {}))

    def save_profile(self, profile: Profile):
        self.set_setting("profile", profile.model_dump())

    def add_source(self, source: Source):
        with self.connect() as db:
            db.execute(
                "INSERT INTO sources(provider,board,company) VALUES (?,?,?) "
                "ON CONFLICT(provider,board) DO NOTHING",
                (source.provider, source.board, source.company),
            )

    def sources(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM sources ORDER BY company")]

    def toggle_source(self, source_id: int, enabled: bool):
        with self.connect() as db:
            return db.execute(
                "UPDATE sources SET enabled=? WHERE id=?", (enabled, source_id)
            ).rowcount

    def ingest(self, source_id: int, jobs: list[dict]):
        timestamp, added, changed = now(), 0, 0
        with self.connect() as db:
            # A successful complete feed is authoritative only for this source.
            db.execute("UPDATE jobs SET active=0 WHERE source_id=?", (source_id,))
            for job in jobs:
                jid = fingerprint([source_id, job["external_id"]])
                version = fingerprint(job)
                previous = db.execute("SELECT version FROM jobs WHERE id=?", (jid,)).fetchone()
                added += previous is None
                changed += previous is not None and previous["version"] != version
                db.execute(
                    """INSERT INTO jobs(id,source_id,data,version,first_seen,last_seen)
                    VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    data=excluded.data, version=excluded.version, last_seen=excluded.last_seen,
                    active=1, review=CASE WHEN jobs.version=excluded.version
                    THEN jobs.review ELSE NULL END""",
                    (jid, source_id, json.dumps(job), version, timestamp, timestamp),
                )
            db.execute("UPDATE sources SET checked=?,error=NULL WHERE id=?", (timestamp, source_id))
        return {"added": added, "changed": changed, "found": len(jobs)}

    def source_error(self, source_id: int, error: str):
        with self.connect() as db:
            db.execute("UPDATE sources SET error=? WHERE id=?", (error[:500], source_id))

    def jobs(self):
        profile = self.profile()
        version = fingerprint(profile.model_dump())
        with self.connect() as db:
            rows = db.execute("""SELECT jobs.*, sources.enabled, sources.error AS source_error,
                              sources.provider FROM jobs JOIN sources
                              ON jobs.source_id=sources.id""").fetchall()
        result = []
        for row in rows:
            item = {
                **json.loads(row["data"]),
                **{
                    key: row[key]
                    for key in [
                        "id",
                        "version",
                        "first_seen",
                        "last_seen",
                        "active",
                        "status",
                        "reason",
                        "source_id",
                        "enabled",
                        "source_error",
                        "provider",
                    ]
                },
            }
            item["match"] = match(item, profile)
            review = json.loads(row["review"]) if row["review"] else None
            item["review"] = review if review and review["profile_version"] == version else None
            result.append(item)
        return sorted(
            result,
            key=lambda j: (j["match"]["eligible"], j["match"]["score"], j["first_seen"]),
            reverse=True,
        )

    def job(self, jid):
        return next((job for job in self.jobs() if job["id"] == jid), None)

    def decision(self, jid, status, reason):
        with self.connect() as db:
            return db.execute(
                "UPDATE jobs SET status=?,reason=? WHERE id=?", (status, reason, jid)
            ).rowcount

    def review(self, jid, review):
        with self.connect() as db:
            db.execute("UPDATE jobs SET review=? WHERE id=?", (json.dumps(review), jid))

    def begin_run(self):
        with self.connect() as db:
            return db.execute(
                "INSERT INTO runs(started,status) VALUES (?, 'running')", (now(),)
            ).lastrowid

    def end_run(self, run_id, status, result):
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET finished=?,status=?,result=? WHERE id=?",
                (now(), status, json.dumps(result), run_id),
            )

    def recover_runs(self):
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status='interrupted',finished=? WHERE status='running'", (now(),)
            )

    def runs(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 10").fetchall()
        return [
            {**dict(row), "result": json.loads(row["result"]) if row["result"] else None}
            for row in rows
        ]
