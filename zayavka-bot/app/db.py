from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns():
    """
    Lightweight, additive-only migration: Base.metadata.create_all() only
    creates tables that don't exist yet, it never alters an existing table's
    columns. Since this project has no Alembic migrations, new nullable
    columns added to a model (e.g. Zayavka.inspector) need this so an
    existing zayavka.db picks them up without losing already-saved rows.
    """
    inspector = inspect(engine)
    if "zayavkalar" not in inspector.get_table_names():
        return  # fresh database - create_all() below will define it fully

    existing = {col["name"] for col in inspector.get_columns("zayavkalar")}
    missing = {
        "inspector": "VARCHAR(255)",
        "cashier": "VARCHAR(255)",
        "tech_supervisor": "VARCHAR(255)",
        "deleted_at": "DATETIME",
        "deleted_by": "VARCHAR(255)",
    }
    with engine.begin() as conn:
        for name, coltype in missing.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE zayavkalar ADD COLUMN {name} {coltype}"))


def _add_missing_indexes():
    """
    create_all() never adds an index to a table that already exists, so a
    database created before these columns were indexed needs them added
    here. Without the items.zayavka_id index, loading each zayavka's items
    scans the whole items table - the list got ~45x slower at 20,000
    zayavkas. Names match what SQLAlchemy generates for index=True on a
    fresh database, and IF NOT EXISTS makes this a no-op on later starts.
    """
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_zayavka_items_zayavka_id ON zayavka_items (zayavka_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_zayavkalar_created_at ON zayavkalar (created_at)"
        ))


# Columns the users table gained after it was first created, with their SQL
# type + default (existing rows get the default, i.e. today's behaviour).
_APP_USER_NEW_COLUMNS = {
    "last_seen_at": "DATETIME",
    "phone": "VARCHAR(20)",
    "role": "VARCHAR(10) NOT NULL DEFAULT 'user'",
    "objects_json": "TEXT NOT NULL DEFAULT '[]'",
    "can_view": "BOOLEAN NOT NULL DEFAULT 1",
    "can_view_others": "BOOLEAN NOT NULL DEFAULT 0",
    "can_view_all_objects": "BOOLEAN NOT NULL DEFAULT 1",
    "can_create": "BOOLEAN NOT NULL DEFAULT 1",
    "can_report": "BOOLEAN NOT NULL DEFAULT 1",
    "can_manage_lists": "BOOLEAN NOT NULL DEFAULT 1",
    "can_manage_users": "BOOLEAN NOT NULL DEFAULT 0",
}


def _migrate_app_users():
    """
    Brings an existing app_users table up to date. telegram_id used to be NOT
    NULL; people invited by phone number don't have one yet, and SQLite can't
    relax a column in place, so that case rebuilds the table (rows are copied).
    Otherwise it only adds the missing columns.
    """
    inspector = inspect(engine)
    if "app_users" not in inspector.get_table_names():
        return  # fresh database - create_all() defines it fully

    columns = {col["name"]: col for col in inspector.get_columns("app_users")}
    if columns["telegram_id"]["nullable"]:
        with engine.begin() as conn:
            for name, coltype in _APP_USER_NEW_COLUMNS.items():
                if name not in columns:
                    conn.execute(text(f"ALTER TABLE app_users ADD COLUMN {name} {coltype}"))
        return

    old_names = list(columns)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE app_users RENAME TO app_users_old"))
        conn.execute(text("DROP INDEX IF EXISTS ix_app_users_telegram_id"))
        conn.execute(text("DROP INDEX IF EXISTS ix_app_users_id"))
    Base.metadata.tables["app_users"].create(bind=engine)
    new_names = {c.name for c in Base.metadata.tables["app_users"].columns}
    shared = ", ".join(n for n in old_names if n in new_names)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO app_users ({shared}) SELECT {shared} FROM app_users_old"))
        conn.execute(text("DROP TABLE app_users_old"))


def init_db():
    from app import models  # noqa: F401  (ensure models are registered)
    _add_missing_columns()
    _migrate_app_users()
    Base.metadata.create_all(bind=engine)
    _add_missing_indexes()
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_app_users_phone ON app_users (phone)"))
