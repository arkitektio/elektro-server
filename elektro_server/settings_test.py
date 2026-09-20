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
AUTHENTIKATE = {
    **AUTHENTIKATE,
    "allow_static_tokens_in_production": True,
    "static_tokens": {
        "test": {"sub": "1"},
        # A non-privileged user in a different organization, for cross-tenant
        # scoping/permission tests. roles must be set explicitly: StaticToken
        # defaults roles to ["admin"], which would let this user delete anything
        # (can_delete rule 1) and defeat the cross-org denial tests.
        "othertest": {"sub": "9", "org": "other_org", "roles": []},
        # A non-admin user in the SAME organization, for delete-ownership tests: holding
        # only "bot", neither rule 1 (admin) nor rule 3 (a bot's creations belong to the
        # task's assigner) lets them delete, so the guard's denial path is reachable.
        "bottest": {"sub": "2", "roles": ["bot"]},
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
# Datalayer() reads this dict (see datalayer/datalayer.py: DatalayerConfig).
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

# The embedding healer re-embeds stale rows in the background. Tests call
# ``embeddings.healer.reembed_stale`` explicitly instead, so a pass can never race an assertion.
EMBEDDINGS_HEALER_ENABLED = False
