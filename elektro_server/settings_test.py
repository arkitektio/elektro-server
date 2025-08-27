from .settings import *  # noqa
from .settings import DATABASES, AUTHENTIKATE
import logging

DATABASES["default"] = {
    "ENGINE": "django.db.backends.sqlite3", 
    "NAME": ":memory:",
    "OPTIONS": {
        "timeout": 30,
    },
    "TEST": {
        "NAME": ":memory:",
    }
}
AUTHENTIKATE = {**AUTHENTIKATE, "STATIC_TOKENS": {"test": {"sub": "1"}}}

# Disable migrations for faster tests
class DisableMigrations:
    """Disable migrations during testing for faster test execution."""
    
    def __contains__(self, item: str) -> bool:
        """Check if item is in migration modules."""
        return True
    
    def __getitem__(self, item: str) -> None:
        """Get migration module for item."""
        return None

# For faster test execution, you can uncomment this:
# MIGRATION_MODULES = DisableMigrations()

# Disable logging during tests to reduce noise
logging.disable(logging.CRITICAL)

# Enable database access from async code in tests
DATABASE_ROUTERS = []

# Use in-memory channel layer for tests instead of Redis
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}
