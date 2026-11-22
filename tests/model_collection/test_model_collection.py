"""createModelCollection executed against the schema."""

import pytest
from kante.context import HttpContext

from core.models import ModelCollection
from tests.fixture_types import AExecute, NeuronModelFactory

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_MODEL_COLLECTION = """
mutation ($input: CreateModelCollectionInput!) {
  createModelCollection(input: $input) { id name }
}
"""


async def test_create_model_collection(
    aexecute: AExecute, make_neuron_model: NeuronModelFactory
) -> None:
    nm = await make_neuron_model()
    res = await aexecute(
        CREATE_MODEL_COLLECTION,
        {"input": {"name": "Collection", "models": [str(nm.id)]}},
    )
    assert not res.errors, res.errors
    assert res.data is not None
    assert res.data["createModelCollection"]["name"] == "Collection"
    assert await ModelCollection.objects.filter(name="Collection").aexists()


async def test_create_model_collection_empty_models(aexecute: AExecute) -> None:
    # No member models is allowed (the m2m is just left empty).
    res = await aexecute(
        CREATE_MODEL_COLLECTION, {"input": {"name": "Empty", "models": []}}
    )
    assert not res.errors, res.errors


async def test_create_model_collection_missing_name(aexecute: AExecute) -> None:
    res = await aexecute(CREATE_MODEL_COLLECTION, {"input": {"models": []}})
    assert res.errors


DATED = """
query {
  modelCollections(ordering: [{ createdAt: DESC }]) { id createdAt creator { sub } }
  neuronModels(ordering: [{ createdAt: DESC }]) { id createdAt creator { sub } }
}
"""


async def test_collections_and_models_say_when_and_by_whom_they_were_made(
    aexecute: AExecute,
    make_neuron_model: NeuronModelFactory,
    authenticated_context: HttpContext,
) -> None:
    """A member's profile feed merges services by date: both need their creation time and maker on the type."""
    nm = await make_neuron_model()
    made = await aexecute(
        CREATE_MODEL_COLLECTION,
        {"input": {"name": "Collection", "models": [str(nm.id)]}},
    )
    assert not made.errors, made.errors

    res = await aexecute(DATED)
    assert not res.errors, res.errors
    assert res.data is not None
    (collection,) = res.data["modelCollections"]
    model = next(row for row in res.data["neuronModels"] if row["id"] == str(nm.id))
    assert collection["createdAt"] and model["createdAt"]
    assert collection["creator"] == {"sub": authenticated_context.request.user.sub}
