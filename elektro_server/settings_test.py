from .settings import *  # noqa
from .settings import DATABASES, AUTHENTIKATE
import logging

DATABASES["default"] = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "testdb",
    "USER": "test",
    "PASSWORD": "test",
    "HOST": "localhost",
    "PORT": "5555",
}
AUTHENTIKATE = {
    **AUTHENTIKATE,
    "STATIC_TOKENS": {
        "test": {"sub": "1"},
        # A user in a different organization, for cross-tenant scoping tests.
        "othertest": {"sub": "9", "active_org": "other_org"},
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
    "port": 6890,
    "protocol": "http",
    "region": "us-east-1",
    "zarr": {"bucket": "zarr"},
    "parquet": {"bucket": "parquet"},
    "media": {"bucket": "media"},
    "bigfile": {"bucket": "media"},
}
