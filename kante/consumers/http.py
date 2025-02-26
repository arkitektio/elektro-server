from strawberry.channels import GraphQLHTTPConsumer
from strawberry.channels.handlers.http_handler import ChannelsRequest
from strawberry.http.temporal_response import TemporalResponse
from kante.context import (
    ChannelsContext,
    EnhancendChannelsHTTPRequest,
)
from authentikate.utils import authenticate_header_or_none
from koherent.utils import get_assignation_id_or_none
from asgiref.sync import sync_to_async
import logging

logger = logging.getLogger(__name__)


class KanteHTTPConsumer(GraphQLHTTPConsumer):
    pass

    async def get_context(
        self, request: ChannelsRequest, response: TemporalResponse
    ) -> ChannelsContext:
        try:
            logger.error(request.headers)
            auth = await sync_to_async(authenticate_header_or_none)(request.headers)
            if auth:
                user = auth.user
                app = auth.app
                scopes = auth.token.scopes
                is_session = False

            else:
                user = request.consumer.scope.get("user", None)
                is_session = "session" in request.consumer.scope
                app = None
                scopes = None

            assignation_id = get_assignation_id_or_none(request.headers)

            return ChannelsContext(
                request=EnhancendChannelsHTTPRequest(
                    consumer=request.consumer,
                    body=request.body,
                    user=user,
                    auth=auth,
                    app=app,
                    scopes=scopes,
                    is_session=is_session,
                    assignation_id=assignation_id,
                ),
                response=response,
            )
        except Exception as e:
            logger.error("Error in http get_contexts", exc_info=True)
            raise e
