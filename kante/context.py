from strawberry.channels import ChannelsConsumer, ChannelsRequest
from strawberry.http.temporal_response import TemporalResponse
from dataclasses import dataclass
from typing import Any, Dict, Optional
from authentikate.models import App, User
from authentikate.structs import Auth


@dataclass
class EnhancendChannelsHTTPRequest(ChannelsRequest):
    user: Optional[User] = None
    app: Optional[App] = None
    scopes: Optional[list[str]] = None
    assignation_id: Optional[str] = None
    auth: Optional[Auth] = None
    is_session: bool = False

    def has_scopes(self, scopes: list[str]) -> bool:
        if self.is_session:
            return True

        if self.scopes is None:
            return False

        return all(scope in self.scopes for scope in scopes)


@dataclass
class ChannelsContext:
    request: EnhancendChannelsHTTPRequest
    response: TemporalResponse

    @property
    def session(self):
        # Depends on Channels' SessionMiddleware / AuthMiddlewareStack
        if "session" in self.request.consumer.scope:
            return self.request.consumer.scope["session"]

        return None


@dataclass
class EnhancendChannelsWSRequest:
    user: Optional[User] = None
    app: Optional[App] = None
    scopes: Optional[list[str]] = None
    assignation_id: Optional[str] = None
    auth: Optional[Auth] = None


@dataclass
class ChannelsWSContext:
    request: EnhancendChannelsWSRequest
    consumer: ChannelsConsumer
    connection_params: Optional[Dict[str, Any]] = None

    @property
    def ws(self) -> ChannelsConsumer:
        return self.request
