import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "elektro_server.settings")
from django.core.asgi import get_asgi_application
# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()


from .schema import schema  # noqa: E402
from kante.router import router # noqa: E402


application = router(
    schema=schema,
    django_asgi_app=django_asgi_app,
    
)