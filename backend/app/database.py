import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite for local dev / demo. Swap DATABASE_URL for a Postgres DSN in production
# (e.g. postgresql+psycopg2://user:pass@host/kavach) -- no model changes needed,
# SQLAlchemy abstracts the dialect.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./kavach.db")

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


COLUMN_RENAMES = [
    ("elements", "location_km", "location_m"),
    ("tags", "location_km", "location_m"),
    ("tins", "start_km", "start_m"),
    ("tins", "end_km", "end_m"),
]


def ensure_schema_up_to_date():
    """Lightweight, SQLite-only 'poor man's migration': adds any columns that exist
    on the current ORM models but not yet in an existing database file, so a user
    upgrading this codebase on top of a kavach.db from an earlier version doesn't
    have to delete their data (their users, existing stations, etc.) every time a
    field gets added -- which was happening far too often during this project's
    development to leave unaddressed.

    This is NOT a substitute for a real migration tool (Alembic) if this platform
    grows beyond a single-developer/pilot deployment -- it only handles "add a
    nullable column", not renames, type changes, or data backfills. It is a
    no-op against a fresh database (Base.metadata.create_all already creates
    every column correctly for a table that doesn't exist yet) and a no-op for
    non-SQLite databases (Postgres deployments should use a real migration tool).
    """
    from sqlalchemy import inspect, text

    # Column RENAMES (any dialect -- ALTER TABLE ... RENAME COLUMN works on SQLite
    # >= 3.25 and on Postgres). Chainage fields were renamed from *_km to *_m when the
    # team confirmed locations are recorded in METRES (e.g. 262910 = km 262.910). The
    # stored values are unchanged -- they were already metres; only the names lied.
    renamed = False
    inspector = inspect(engine)
    tables_now = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, old_col, new_col in COLUMN_RENAMES:
            if table not in tables_now:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if old_col in cols and new_col not in cols:
                print(f"[schema migration] renaming '{table}.{old_col}' -> '{new_col}'")
                conn.execute(text(f'ALTER TABLE "{table}" RENAME COLUMN "{old_col}" TO "{new_col}"'))
                renamed = True
            elif old_col in cols and new_col in cols:
                # Both exist: an intermediate run (e.g. a dev-server auto-reload that
                # picked up the new models before this migration) ADDED an empty new
                # column. Copy the real values across so nothing is silently lost; the
                # old column is left in place (harmless, and a record of the move).
                n = conn.execute(text(
                    f'UPDATE "{table}" SET "{new_col}" = "{old_col}" '
                    f'WHERE "{new_col}" IS NULL AND "{old_col}" IS NOT NULL')).rowcount
                if n:
                    print(f"[schema migration] copied {n} value(s) '{table}.{old_col}' -> '{new_col}'")
                # The old column is NOT NULL, so it must go or every new insert fails.
                conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{old_col}"'))
                print(f"[schema migration] dropped superseded column '{table}.{old_col}'")
    if renamed:
        inspector = inspect(engine)  # refresh cached column info

    if not DATABASE_URL.startswith("sqlite"):
        return

    existing_tables = set(inspector.get_table_names())

    # Import here (not at module load) to avoid a circular import with models.py,
    # which imports Base from this module.
    from . import models  # noqa: F401 -- ensures Base.metadata is fully populated

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand-new table -- create_all() already handles this correctly
            existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                print(f"[schema migration] adding missing column '{column.name}' "
                      f"to table '{table.name}'")
                conn.execute(text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                ))
