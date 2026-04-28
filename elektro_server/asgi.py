import os

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

application = OpenTelemetryMiddleware(
    router(schema=schema, django_asgi_app=django_asgi_app)
)
