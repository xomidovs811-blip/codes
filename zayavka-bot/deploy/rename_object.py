"""
Renames a building object (Название объекта) everywhere it is used:
  - the object list the bot offers (an object added through the bot),
  - every zayavka filed under it (so filters/reports keep finding them),
  - users whose access is limited to chosen objects.
Saved version history (Tarix) is left as it was sent. The Номер заявки of
existing zayavkas does not change.

Run from the zayavka-bot folder:
  .venv\\Scripts\\python.exe deploy\\rename_object.py "old name" "new name"           (preview only)
  .venv\\Scripts\\python.exe deploy\\rename_object.py "old name" "new name" --apply   (do it)

The old name is matched ignoring upper/lower case. Restart the bot and the
API afterwards so the new list shows up everywhere.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import OBJECTS  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import AppUser, NameOption, Zayavka  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--apply"]
    apply = "--apply" in sys.argv[1:]
    if len(args) != 2 or not args[0].strip() or not args[1].strip():
        print(__doc__)
        return 2
    old_in, new = args[0].strip(), args[1].strip()

    init_db()
    db = SessionLocal()
    try:
        # every spelling of the old name actually in use (case-insensitive)
        seen = {o.name for o in db.query(NameOption).filter(NameOption.category == "object")}
        seen |= {z for (z,) in db.query(Zayavka.object_name).distinct()}
        olds = sorted(n for n in seen if n.casefold() == old_in.casefold() and n != new)
        if not olds:
            print(f"Object '{old_in}' not found. Objects in use:")
            for n in sorted(seen):
                print("  -", n)
            return 1
        if any(o in OBJECTS for o in olds):
            print(f"'{olds}' is in the fixed list in app/config.py (OBJECTS) - edit it there as well.")

        options = db.query(NameOption).filter(NameOption.category == "object", NameOption.name.in_(olds)).all()
        zayavkas = db.query(Zayavka).filter(Zayavka.object_name.in_(olds)).all()
        users = [u for u in db.query(AppUser).all() if set(u.objects) & set(olds)]

        print(f"Rename {olds} -> '{new}':")
        print(f"  object list entries: {len(options)}")
        print(f"  zayavkas:            {len(zayavkas)}")
        print(f"  users' object access: {len(users)}" + (f" ({', '.join(u.name or str(u.id) for u in users)})" if users else ""))
        if not apply:
            print("\nPreview only - nothing changed. Add --apply to rename.")
            return 0

        exists = db.query(NameOption).filter(NameOption.category == "object", NameOption.name == new).first()
        for opt in options:
            if exists:
                db.delete(opt)          # the new name is already listed - just drop the old entry
            else:
                opt.name = new
                exists = opt
        if not exists and new not in OBJECTS:
            db.add(NameOption(category="object", name=new))
        for z in zayavkas:
            z.object_name = new
        for u in users:
            u.objects = [new if o in olds else o for o in u.objects]
        db.commit()
        print("\nDone. Now restart the bot and the API.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
