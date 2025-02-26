from .settings import *  # noqa
from .settings import DATABASES, AUTHENTIKATE

DATABASES["default"] = {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
AUTHENTIKATE = {**AUTHENTIKATE, "STATIC_TOKENS": {"test": {"sub": "1"}}}
