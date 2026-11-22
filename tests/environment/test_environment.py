"""ModEnvironment mutations executed against the schema:
createModEnvironment (BigFileStore-backed, local fill_info).

Note: delete_mechanism exists as a resolver but is not wired into the schema
Mutation type, so there is no `deleteMechanism` field to test here.
"""

import pytest

from core.models import Mechanism, ModEnvironment
from tests.fixture_types import AExecute, BigFileStoreFactory

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_MOD_ENVIRONMENT = """
mutation ($input: CreateModEnvironmentInput!) {
  createModEnvironment(input: $input) { id name }
}
"""


async def test_create_mod_environment(
    aexecute: AExecute, bigfile_store: BigFileStoreFactory
) -> None:
    store = await bigfile_store()
    res = await aexecute(
        CREATE_MOD_ENVIRONMENT,
        {
            "input": {
                "name": "Env",
                "zipFile": str(store.id),
                "mechanisms": [{"name": "mech1", "parameters": []}],
            }
        },
    )
    assert not res.errors, res.errors
    assert res.data is not None
    assert res.data["createModEnvironment"]["name"] == "Env"
    env = await ModEnvironment.objects.aget(name="Env")
    assert await Mechanism.objects.filter(environment=env, name="mech1").aexists()


# --- negatives ---------------------------------------------------------------


async def test_create_mod_environment_unknown_store(aexecute: AExecute) -> None:
    res = await aexecute(
        CREATE_MOD_ENVIRONMENT,
        {"input": {"name": "Bad", "zipFile": "999999", "mechanisms": []}},
    )
    assert res.errors
