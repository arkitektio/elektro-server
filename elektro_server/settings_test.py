import os
from .settings import *  # noqa
from .settings import DATABASES, AUTHENTIKATE
import logging

DATABASES["default"] = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "testdb",
    "USER": "test",
    "PASSWORD": "test",
    "HOST": "localhost",
    # A placeholder for a hand-started stack; under pytest `django_db_modify_db_settings`
    # overwrites it with the port docker picked (see tests/conftest.py). Point
    # ELEKTRO_TEST_DB_PORT at `docker compose port db 5432` to run against your own stack.
    "PORT": os.environ.get("ELEKTRO_TEST_DB_PORT", "5555"),
}
# Django forces DEBUG=False under the test runner, and authentikate 3.0 refuses static
# tokens when DEBUG is False. These are deliberate test fixtures, so opt in explicitly.
#: What a test token is unless it says otherwise: elektro's admin, through an app granted all of elektro.
ADMIN_WITH_EVERY_SCOPE = {"roles": ["elektro_admin"], "scope": "openid elektro_all"}

AUTHENTIKATE = {
    **AUTHENTIKATE,
    "allow_static_tokens_in_production": True,
    # This service instance, as konstruktor renders it: what a guest's collaborations are
    # listed under (tests/test_sharing.py).
    "audience": "1",
    "static_tokens": {
        name: {**ADMIN_WITH_EVERY_SCOPE, **token}
        for name, token in {
            "test": {"sub": "1"},
            # A non-privileged user in a different organization, for cross-tenant
            # scoping/permission tests: an editor passes the write gate, but is not elektro's
            # admin, who may delete anything (can_delete rule 1) and would defeat the
            # cross-org denial tests.
            "othertest": {"sub": "9", "org": "other_org", "roles": ["elektro_editor"]},
            # The SAME user as "test", acting in the other organization: a user who belongs to
            # two orgs must only ever see the rows of the org they are acting in.
            "test-other-org": {"sub": "1", "org": "other_org"},
            # A non-admin user in the SAME organization, for delete-ownership tests: an editor
            # passes the write gate but is not elektro's admin, so the creator/assigner guard
            # actually applies to them.
            "bottest": {"sub": "2", "roles": ["elektro_editor"]},
            # An editor: writes data and requests upload grants, but is not elektro's admin.
            "editortest": {"sub": "3", "roles": ["elektro_editor"]},
            # In the org, but holding no role that may write or upload.
            "viewertest": {"sub": "4", "roles": []},
            # An app granted only what it reads, for the scope tests (tests/test_scopes.py).
            "readertest": {"sub": "1", "scope": "openid elektro_read"},
        }.items()
    },
}

OPENTELEMETRY_EXPORTER_OTLP_ENDPOINT = "http://localhost:4317"


# Disable migrations for faster tests
class DisableMigrations:
    """Disable migrations during testing for faster test execution."""

    def __contains__(self, item: str) -> bool:
        """Check if item is in migration modules."""
        return True

    def __getitem__(self, item: str) -> None:
        """Get migration module for item."""
        return None


MIGRATION_MODULES = DisableMigrations()

# Disable logging during tests to reduce noise
logging.disable(logging.CRITICAL)

# Enable database access from async code in tests
DATABASE_ROUTERS = []

# Use in-memory channel layer for tests instead of Redis
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Point the datalayer at the MinIO service from tests/integration/docker-compose.yaml
# (buckets + user are provisioned by the `initc` init container / configs/minio.yaml).
# Datalayer() reads this dict (see arkitekt_datalayer.datalayer.DatalayerConfig).
DATALAYER = {
    "access_key": "mikro_access_key",
    "secret_key": "mikro_secret_key",
    "host": "localhost",
    "port": int(os.environ.get("ELEKTRO_TEST_RUSTFS_PORT", "6890")),  # overwritten under pytest, like PORT above
    "protocol": "http",
    "region": "us-east-1",
    "zarr": {"bucket": "zarr"},
    "parquet": {"bucket": "parquet"},
    "media": {"bucket": "media"},
    "bigfile": {"bucket": "media"},
    # No `role_arn`, so no session can be assumed and a grant would now refuse rather than
    # quietly return the static key above. Tests exercising a grant care about its shape.
    "allow_unscoped_fallback": True,
}

