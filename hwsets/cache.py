"""SQLite cache keyed by a hash of the PDF bytes."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

PIPELINE_VERSION = "1.0"
DEFAULT_PATH = Path(__file__).resolve().parents[1] / ".cache" / "hwsets.sqlite"


def file_fingerprint(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Cache:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the API's worker thread and request handlers share it.
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
        self.db.execute("CREATE TABLE IF NOT EXISTS results (key TEXT PRIMARY KEY, json TEXT, created REAL)")
        self.db.commit()

    @staticmethod
    def key(*parts) -> str:
        h = hashlib.sha256()
        for p in parts:
            h.update(p if isinstance(p, bytes) else str(p).encode())
            h.update(b"\x00")
        return h.hexdigest()

    def result_key(self, pdf_path: str | Path, pages) -> str:
        return self.key(file_fingerprint(pdf_path), PIPELINE_VERSION, pages)

    def _get(self, table: str, key: str):
        row = self.db.execute(f"SELECT json FROM {table} WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _put(self, table: str, key: str, value) -> None:
        self.db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?)", (key, json.dumps(value), time.time()))
        self.db.commit()

    def get_result(self, key: str):
        return self._get("results", key)

    def put_result(self, key: str, value) -> None:
        self._put("results", key, value)

