import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "elektro_server.settings")
from django.core.asgi import get_asgi_application

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()
# OpenTelemetry Imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from .schema import schema  # noqa: E402
from core import models  # noqa: E402
from embeddings.healer import ensure_healer_started  # noqa: E402
from kante.router import router  # noqa: E402
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware  # noqa: E402
from opentelemetry.instrumentation.django import DjangoInstrumentor

# Add DB instrumentation (assuming psycopg2 for Postgres; change if using sqlite/mysql)
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from django.conf import settings

# --- 1. Configure the Exporter ---
# Set up the global provider
provider = TracerProvider()


trace.set_tracer_provider(provider)
# Replace the ConsoleSpanExporter with OTLP:
otlp_exporter = OTLPSpanExporter(
    endpoint=settings.OPENTELEMETRY_EXPORTER_OTLP_ENDPOINT, insecure=True
)
processor = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)


# --- 2. Instrument Internal Libraries ---
# This cracks open the "black box" to show views, templates, and middleware
DjangoInstrumentor().instrument()


# This reveals the exact SQL queries causing delays
if PsycopgInstrumentor:
    PsycopgInstrumentor().instrument()

_routed_application = OpenTelemetryMiddleware(
    router(schema=schema, django_asgi_app=django_asgi_app, schema_path="schema")
)


# --- The embedding healer (``embeddings.healer``) --------------------------------------------
# Rows whose vector was produced by another embedding model (or none: written before
# embeddings were on, or while the weights were unreachable) are re-embedded by a loop inside
# THIS process, in row-locked batches -- no management command, no cron, no sidecar, and any
# number of replicas may run it side by side (``skip_locked`` keeps their claims disjoint).
#
# Daphne implements no ASGI ``lifespan``, but it installs its asyncio-backed Twisted reactor
# before importing this module, so ``callWhenRunning`` starts the loop the moment the server's
# event loop is up. The scope wrapper below is the server-agnostic fallback; both are
# idempotent. Off under the test suite (``EMBEDDINGS_HEALER_ENABLED``), which drives the
# healer explicitly.
_EMBEDDED_MODELS = (models.ArrayDataset, models.TableDataset, models.SparseDataset)


def _start_healer() -> None:
    if getattr(settings, "EMBEDDINGS_HEALER_ENABLED", True):
        ensure_healer_started(_EMBEDDED_MODELS, interval=settings.EMBEDDINGS["SWEEP_INTERVAL"])


if "twisted.internet.reactor" in sys.modules:
    sys.modules["twisted.internet.reactor"].callWhenRunning(_start_healer)


async def application(scope, receive, send):  # noqa: ANN001, ANN201
    """The routed ASGI app, starting the healer on the first scope if nothing did before."""
    _start_healer()
    return await _routed_application(scope, receive, send)
