"""Local storage and atomic publication primitives."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[2]


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default


@contextmanager
def atomic_text(path, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding=encoding, newline="", dir=path.parent, delete=False
    ) as output:
        temporary = Path(output.name)
        try:
            with output:
                yield output
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def write_json(path, payload):
    with atomic_text(path) as output:
        json.dump(payload, output, ensure_ascii=True, indent=2, allow_nan=False)
        output.write("\n")


@contextmanager
def writer_lock(directory):
    """Hold a process-safe local lock. SQLite releases it if the writer exits."""
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / ".writer.sqlite3", timeout=5)
    try:
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_BUSY:
                raise RuntimeError("Another writer is using this data directory") from None
            raise
        yield
    finally:
        connection.close()
