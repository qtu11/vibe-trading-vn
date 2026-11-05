"""A read-only recovery barrier shared with the legacy SDK order gate."""

import sqlite3
from src.config.paths import get_runtime_root


def has_pending(connector: str) -> bool:
    path = get_runtime_root() / "forex" / "execution.db"
    if not path.exists():
        return False
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            return (
                db.execute(
                    "SELECT 1 FROM intents WHERE connector=? AND state IN ('submitting','accepted','working','partial','unknown') LIMIT 1",
                    (connector,),
                ).fetchone()
                is not None
            )
        finally:
            db.close()
    except sqlite3.Error:
        return True  # An unreadable journal cannot authorize another write.
