from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

settings = get_settings()

engine_kwargs = {
    "echo": settings.DEBUG,
    "future": True,
}

if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs,
)

async_session_maker = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    from app.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _alembic_heads() -> set[str]:
    backend_root = Path(__file__).resolve().parent.parent
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def assert_database_revision_current() -> None:
    """Fail startup when a migration-managed database is not at the code head."""
    expected_heads = _alembic_heads()
    if len(expected_heads) != 1:
        raise RuntimeError(
            "Alembic revision chain must have exactly one head; "
            f"found: {', '.join(sorted(expected_heads)) or 'none'}"
        )

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            database_heads = {str(row[0]) for row in result.fetchall()}
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Database schema version cannot be verified. "
            "Run `python -m alembic upgrade head` before starting the application; "
            "automatic schema changes are disabled."
        ) from exc

    if database_heads != expected_heads:
        raise RuntimeError(
            "Database schema is not current. "
            f"Expected Alembic head {', '.join(sorted(expected_heads))}; "
            f"database reports {', '.join(sorted(database_heads)) or 'no revision'}. "
            "Run `python -m alembic upgrade head` before starting the application."
        )
