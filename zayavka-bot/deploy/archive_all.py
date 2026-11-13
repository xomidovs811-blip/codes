"""
Writes the "Zayavkalar" backup archive for every zayavka now (the API also
does this by itself on every start, in the background). Only files that are
missing or out of date are written, so running it again is quick.

Run from the zayavka-bot folder:
  .venv\\Scripts\\python.exe deploy\\archive_all.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.archive import sync_archive  # noqa: E402
from app.config import ARCHIVE_DIR  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Zayavka  # noqa: E402
from app.services import backfill_versions  # noqa: E402


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        backfill_versions(db)
        total = db.query(Zayavka).count()
    finally:
        db.close()
    written = sync_archive()
    files = sum(
        1 for month in os.listdir(ARCHIVE_DIR) if os.path.isdir(os.path.join(ARCHIVE_DIR, month))
        for name in os.listdir(os.path.join(ARCHIVE_DIR, month)) if name.lower().endswith(".xlsx")
    ) if os.path.isdir(ARCHIVE_DIR) else 0
    print(f"Archive folder: {os.path.abspath(ARCHIVE_DIR)}")
    print(f"Zayavkas in the system: {total}")
    print(f"Files written now:      {written}")
    print(f"Files in the archive:   {files}")


if __name__ == "__main__":
    main()
