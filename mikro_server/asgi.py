"""
ASGI config for mikro_server project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/asgi/
"""


import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mikro_server.settings")
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from .basepath import re_basepath
from django.core.asgi import get_asgi_application
from kante.consumers import KanteHTTPConsumer, KanteWsConsumer
from kante.cors import CorsMiddleware
from django.urls import re_path


# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()


from mikro_server.schema import schema  # noqa


gql_http_consumer = CorsMiddleware(
    AuthMiddlewareStack(KanteHTTPConsumer.as_asgi(schema=schema))
)
gql_ws_consumer = KanteWsConsumer.as_asgi(schema=schema)


websocket_urlpatterns = [
    re_basepath(r"graphql", gql_ws_consumer),
]

application = ProtocolTypeRouter(
    {
        "http": URLRouter(
            [
                re_basepath("graphql", gql_http_consumer),
                re_path(
                    "", django_asgi_app
                ),  # This might be another endpoint in your app
            ]
        ),
        # Just HTTP for now. (We can add other protocols later.)
        "websocket": CorsMiddleware(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
