import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app import database
from app.config import Settings
from app.middleware import SecurityHeadersMiddleware
from app.services.release_checks import run_release_checks


class PlatformQualityBaselineTest(unittest.TestCase):
    def test_settings_normalize_csv_security_lists(self) -> None:
        settings = Settings(
            CORS_ALLOW_ORIGINS="https://app.example.com, https://admin.example.com, ",
            TRUSTED_HOSTS="app.example.com, admin.example.com",
        )

        self.assertEqual(
            settings.CORS_ALLOW_ORIGINS,
            ["https://app.example.com", "https://admin.example.com"],
        )
        self.assertEqual(settings.TRUSTED_HOSTS, ["app.example.com", "admin.example.com"])

    def test_agent_run_store_release_contract_fails_closed(self) -> None:
        staging_memory = Settings(
            APP_ENV="staging",
            AGENT_SHADOW_API_ENABLED=True,
            AGENT_RUN_STORE_BACKEND="memory",
        )
        memory_check = next(
            item for item in run_release_checks(staging_memory)["checks"] if item["key"] == "agent_run_store"
        )
        self.assertEqual(memory_check["severity"], "critical")

        mismatched_postgres = Settings(
            AGENT_RUN_STORE_BACKEND="postgresql",
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
        )
        mismatch_check = next(
            item for item in run_release_checks(mismatched_postgres)["checks"] if item["key"] == "agent_run_store"
        )
        self.assertEqual(mismatch_check["severity"], "critical")

        configured_postgres = Settings(
            AGENT_RUN_STORE_BACKEND="postgresql",
            DATABASE_URL="postgresql+asyncpg://user:password@db.example/test",
        )
        configured_check = next(
            item for item in run_release_checks(configured_postgres)["checks"] if item["key"] == "agent_run_store"
        )
        self.assertEqual(configured_check["severity"], "pass")
    def test_production_security_headers_are_enforced(self) -> None:
        app = FastAPI()
        app.add_middleware(
            SecurityHeadersMiddleware,
            settings=Settings(APP_ENV="production"),
        )

        @app.get("/probe")
        async def probe() -> dict[str, bool]:
            return {"ok": True}

        with TestClient(app) as client:
            response = client.get("/probe")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["strict-transport-security"],
            "max-age=31536000; includeSubDomains",
        )
        self.assertEqual(
            response.headers["content-security-policy"],
            "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )


class DatabaseRevisionGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_alembic_heads_fail_startup(self) -> None:
        with patch.object(database, "_alembic_heads", return_value={"0017", "0018"}):
            with self.assertRaisesRegex(RuntimeError, "exactly one head"):
                await database.assert_database_revision_current()

    async def test_unreadable_revision_table_fails_with_migration_guidance(self) -> None:
        class FailingConnectionContext:
            async def __aenter__(self):
                raise SQLAlchemyError("database unavailable")

            async def __aexit__(self, exc_type, exc, traceback):
                return False

        class FailingEngine:
            def connect(self):
                return FailingConnectionContext()

        with (
            patch.object(database, "_alembic_heads", return_value={"0017"}),
            patch.object(database, "engine", FailingEngine()),
        ):
            with self.assertRaisesRegex(RuntimeError, "alembic upgrade head"):
                await database.assert_database_revision_current()

    async def test_stale_database_revision_fails_closed(self) -> None:
        class RevisionResult:
            def fetchall(self):
                return [("0016",)]

        class ConnectedDatabase:
            async def execute(self, statement):
                self.statement = statement
                return RevisionResult()

        class ConnectionContext:
            def __init__(self):
                self.connection = ConnectedDatabase()

            async def __aenter__(self):
                return self.connection

            async def __aexit__(self, exc_type, exc, traceback):
                return False

        class StaleEngine:
            def connect(self):
                return ConnectionContext()

        with (
            patch.object(database, "_alembic_heads", return_value={"0017"}),
            patch.object(database, "engine", StaleEngine()),
        ):
            with self.assertRaisesRegex(RuntimeError, "Expected Alembic head 0017"):
                await database.assert_database_revision_current()


if __name__ == "__main__":
    unittest.main()
