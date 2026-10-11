"""Data model for jobs and human corrections (SQLite).

    jobs          one row per uploaded PDF: queued -> running -> done | failed
    corrections   one row per field a reviewer changed, so we can measure where
                  the extractor is wrong and turn fixes into new answer keys

Extraction results themselves live in the cache (see cache.py), keyed by the
file fingerprint; a job just points at its result.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / ".cache" / "jobs.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    pdf_path    TEXT NOT NULL,
    status      TEXT NOT NULL,          -- queued | running | done | failed
    error       TEXT,
    result_key  TEXT,
    cache_hit   INTEGER,
    created     REAL NOT NULL,
    started     REAL,
    finished    REAL
);
CREATE TABLE IF NOT EXISTS corrections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    set_number  TEXT NOT NULL,
    comp_index  INTEGER NOT NULL,       -- -1 = a set-level field
    field       TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    created     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


class Store:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    # jobs ---------------------------------------------------------------
    def create_job(self, filename: str, pdf_path: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        self.db.execute("INSERT INTO jobs (id, filename, pdf_path, status, created) VALUES (?,?,?,?,?)",
                        (job_id, filename, pdf_path, "queued", time.time()))
        self.db.commit()
        return job_id

    def update_job(self, job_id: str, **fields) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))
        self.db.commit()

    def get_job(self, job_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,))]

    def unfinished_jobs(self) -> list[dict]:
        """Jobs that were queued/running when the server stopped; requeued on start."""
        return [dict(r) for r in self.db.execute("SELECT * FROM jobs WHERE status IN ('queued','running')")]

    # corrections --------------------------------------------------------
    def add_correction(self, source_file: str, set_number: str, comp_index: int, field: str,
                       old_value, new_value) -> None:
        self.db.execute(
            "INSERT INTO corrections (source_file, set_number, comp_index, field, old_value, new_value, created) "
            "VALUES (?,?,?,?,?,?,?)",
            (source_file, set_number, comp_index, field,
             None if old_value is None else str(old_value), None if new_value is None else str(new_value), time.time()))
        self.db.commit()

    def corrections(self, source_file: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM corrections", ()
        if source_file:
            q, args = q + " WHERE source_file = ?", (source_file,)
        return [dict(r) for r in self.db.execute(q + " ORDER BY created", args)]

    def correction_summary(self) -> list[dict]:
        """Which fields people fix most: tells us where the extractor needs work."""
        return [dict(r) for r in self.db.execute(
            "SELECT field, COUNT(*) AS n FROM corrections GROUP BY field ORDER BY n DESC")]
