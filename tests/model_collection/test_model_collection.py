"""createModelCollection executed against the schema."""

import pytest

from core.models import ModelCollection

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_MODEL_COLLECTION = """
mutation ($input: CreateModelCollectionInput!) {
  createModelCollection(input: $input) { id name }
}
"""


async def test_create_model_collection(aexecute, make_neuron_model):
    nm = await make_neuron_model()
    res = await aexecute(
        CREATE_MODEL_COLLECTION,
        {"input": {"name": "Collection", "models": [str(nm.id)]}},
    )
    assert not res.errors, res.errors
    assert res.data["createModelCollection"]["name"] == "Collection"
    assert await ModelCollection.objects.filter(name="Collection").aexists()


async def test_create_model_collection_empty_models(aexecute):
    # No member models is allowed (the m2m is just left empty).
    res = await aexecute(CREATE_MODEL_COLLECTION, {"input": {"name": "Empty", "models": []}})
    assert not res.errors, res.errors


async def test_create_model_collection_missing_name(aexecute):
    res = await aexecute(CREATE_MODEL_COLLECTION, {"input": {"models": []}})
    assert res.errors
