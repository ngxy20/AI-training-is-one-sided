"""Registry SQLite + one isolated SQLite per project (PRD: 项目级元数据库)."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


_engines: dict[str, Engine] = {}
_sessions: dict[str, sessionmaker[Session]] = {}


def _engine(key: str, path: Path) -> Engine:
    if key in _engines:
        return _engines[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    _engines[key] = engine
    _sessions[key] = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return engine


def registry_engine() -> Engine:
    return _engine("registry", config.REGISTRY_DB)


def project_engine(project_id: str) -> Engine:
    return _engine(f"project:{project_id}", config.PROJECTS_DIR / project_id / "meta.db")


def registry_maker() -> sessionmaker[Session]:
    registry_engine()
    return _sessions["registry"]


def project_maker(project_id: str) -> sessionmaker[Session]:
    project_engine(project_id)
    return _sessions[f"project:{project_id}"]


@contextmanager
def registry_session() -> Iterator[Session]:
    session = registry_maker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def project_session(project_id: str) -> Iterator[Session]:
    session = project_maker(project_id)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


REGISTRY_ONLY_TABLES = ("users", "project_members")


def init_registry() -> None:
    from .models import Project, ProjectMember, User  # noqa: F401

    config.bootstrap()
    Base.metadata.create_all(registry_engine(),
                             tables=[Project.__table__, User.__table__, ProjectMember.__table__])


def init_project_db(project_id: str) -> None:
    from . import models  # noqa: F401  (registers every table on Base.metadata)

    tables = [t for t in Base.metadata.sorted_tables
              if t.name != "projects" and t.name not in REGISTRY_ONLY_TABLES]
    Base.metadata.create_all(project_engine(project_id), tables=tables)


def _column_ddl(engine: Engine, column) -> str:
    """SQLite ALTER TABLE ADD COLUMN fragment, including a constant default."""
    import json as _json

    from sqlalchemy.schema import CreateColumn

    fragment = str(CreateColumn(column).compile(dialect=engine.dialect))
    default = column.default
    if default is not None and "DEFAULT" not in fragment.upper():
        value = default.arg
        if callable(value):
            try:
                value = value(None)
            except TypeError:
                value = value()
        if isinstance(value, (dict, list)):
            literal = "'" + _json.dumps(value, ensure_ascii=False).replace("'", "''") + "'"
        elif isinstance(value, bool):
            literal = "1" if value else "0"
        elif isinstance(value, (int, float)):
            literal = str(value)
        elif value is None:
            literal = "NULL"
        else:
            literal = "'" + str(value).replace("'", "''") + "'"
        fragment += f" DEFAULT {literal}"
    if not column.nullable and "NOT NULL" not in fragment.upper():
        if "DEFAULT" in fragment.upper():
            fragment += " NOT NULL"
    return fragment


def _add_missing_columns(engine: Engine) -> int:
    """create_all() only creates new tables; add columns introduced by new models."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added = 0
    for table in Base.metadata.sorted_tables:
        if table.name in ("projects", *REGISTRY_ONLY_TABLES) or table.name not in existing_tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        missing = [column for column in table.columns if column.name not in present]
        if not missing:
            continue
        with engine.begin() as connection:
            for column in missing:
                connection.execute(text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN {_column_ddl(engine, column)}'))
                added += 1
    return added


def migrate_all_projects() -> int:
    """Bring databases of already existing projects up to the current schema."""
    from sqlalchemy import select

    from .models import Project

    with registry_session() as session:
        ids = [p.id for p in session.execute(select(Project)).scalars().all()]
    for project_id in ids:
        init_project_db(project_id)
        _add_missing_columns(project_engine(project_id))
    _add_missing_columns(registry_engine())
    return len(ids)


def dispose_all() -> None:
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
    _sessions.clear()
