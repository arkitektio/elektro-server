import pytest
from core.models import Trace, Dataset
from django.contrib.auth import get_user_model
from elektro_server.schema import schema
from guardian.shortcuts import get_perms
from asgiref.sync import sync_to_async
from kante.context import HttpContext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_dataset_upper(db, authenticated_context: HttpContext):

    dataset = await Dataset.objects.acreate(
        name="Test Model", description="This is a test model",
        creator=authenticated_context.request.user,
        organization=authenticated_context.request.organization,
        membership=authenticated_context.request.membership
    )
    my_model = await Trace.objects.acreate(
        dataset=dataset,
        creator=authenticated_context.request.user,
        organization=authenticated_context.request.organization,
    )


    query = """
        query {
            trace(id: 1) {
                id
                dataset {
                    name 
                }
            }
        }
    """

    sub = await schema.execute(
        query,
        context_value=authenticated_context,
    )

    assert sub.data, sub.errors

    assert sub.data["trace"]["dataset"]["name"] == "Test Model"
