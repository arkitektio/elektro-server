from asgiref.typing import (
    ASGIApplication,
    Scope,
    ASGIReceiveCallable,
    ASGISendCallable,
    ASGISendEvent,
)
from typing import Awaitable


class CorsMiddleware:
    def __init__(self, app: ASGIApplication):
        self.app = app

    async def __call__(
        self, scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ) -> Awaitable[None]:
        if scope["type"] == "http" and scope["method"] == "OPTIONS":
            # preflight request. reply successfully:
            headers = [
                (b"Access-Control-Allow-Origin", b"*"),
                (b"Access-Control-Allow-Headers", b"Authorization, Content-Type"),
                (b"Access-Control-Allow-Methods", b"GET, POST, PUT, DELETE, OPTIONS"),
                (b"Access-Control-Max-Age", b"86400"),
            ]
            await send(
                {"type": "http.response.start", "status": 200, "headers": headers}
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"",
                }
            )
        else:

            async def wrapped_send(event: ASGISendEvent) -> None:
                if event["type"] == "http.response.start":
                    print("Original Event")
                    original_headers = event.get("headers") or []
                    access_control_allow_origin = b"*"

                    if access_control_allow_origin is not None:
                        # Construct a new event with new headers
                        event = {
                            "type": "http.response.start",
                            "status": event["status"],
                            "headers": [
                                p
                                for p in original_headers
                                if p[0] != b"access-control-allow-origin"
                            ]
                            + [
                                [
                                    b"access-control-allow-origin",
                                    access_control_allow_origin,
                                ]
                            ],
                        }

                    print(event)
                await send(event)

            await self.app(scope, receive, wrapped_send)

        return None
