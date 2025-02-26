import pytest
from core.models import Image, Dataset
from django.contrib.auth import get_user_model
from authentikate.models import App
from mikro_server.schema import schema
from guardian.shortcuts import get_perms
from asgiref.sync import sync_to_async
from kante.context import ChannelsContext, EnhancendChannelsHTTPRequest



@pytest.mark.asyncio
async def test_dataset_upper(db, authenticated_context: ChannelsContext):

    dataset = await Dataset.objects.acreate(
        name="Test Model", description="This is a test model",
        creator=authenticated_context.request.user,
    )
    my_model = await Image.objects.acreate(
        dataset=dataset,
        creator=authenticated_context.request.user,
    )


    query = """
        query {
            image(id: 1) {
                id
                dataset {
                    name @upper
                }
            }
        }
    """

    sub = await schema.execute(
        query,
        context_value=authenticated_context,
    )

    assert sub.data, sub.errors

    assert sub.data["image"]["dataset"]["name"] == "TEST MODEL"
