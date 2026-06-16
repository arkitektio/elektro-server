"""Block mutations executed against the schema: createBlock (with a Zarr-backed
analog signal) and deleteBlock."""

import datetime

import pytest

from core.models import Block, Dataset

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_BLOCK = """
mutation ($input: CreateBlockInput!) {
  createBlock(input: $input) { id name }
}
"""

DELETE_BLOCK = """
mutation ($input: DeleteBlockInput!) {
  deleteBlock(input: $input)
}
"""


async def test_create_block_empty(aexecute):
    # No segments -> pure-DB happy path (no object store needed).
    res = await aexecute(CREATE_BLOCK, {"input": {"name": "Block", "segments": []}})
    assert not res.errors, res.errors
    assert res.data["createBlock"]["name"] == "Block"
    assert await Block.objects.filter(name="Block").aexists()


async def test_create_block_with_analog_signal(aexecute, zarr_store):
    time_store = await zarr_store()
    channel_store = await zarr_store()
    res = await aexecute(
        CREATE_BLOCK,
        {
            "input": {
                "name": "BlockSig",
                "segments": [
                    {
                        "analogSignals": [
                            {
                                "name": "sig0",
                                "timeTrace": str(time_store.id),
                                "samplingRate": 1000.0,
                                "tStart": 0.0,
                                "channels": [
                                    {"name": "c0", "index": 0, "trace": str(channel_store.id)}
                                ],
                            }
                        ]
                    }
                ],
            }
        },
    )
    assert not res.errors, res.errors
    assert await Block.objects.filter(name="BlockSig").aexists()


async def test_delete_block(aexecute, authenticated_context):
    ds = await Dataset.objects.acreate(
        name="ds",
        creator=authenticated_context.request.user,
        organization=authenticated_context.request.organization,
        membership=authenticated_context.request.membership,
    )
    block = await Block.objects.acreate(
        name="Doomed",
        dataset=ds,
        recording_time=datetime.datetime.now(),
        organization=authenticated_context.request.organization,
        creator=authenticated_context.request.user,
    )
    res = await aexecute(DELETE_BLOCK, {"input": {"id": str(block.id)}})
    assert not res.errors, res.errors
    assert res.data["deleteBlock"] == str(block.id)
    assert not await Block.objects.filter(id=block.id).aexists()


# --- negatives ---------------------------------------------------------------


async def test_delete_block_not_found(aexecute):
    res = await aexecute(DELETE_BLOCK, {"input": {"id": "999999"}})
    assert res.errors


async def test_create_block_missing_zarr_metadata(aexecute, zarr_store):
    time_store = await zarr_store(seed=False)
    res = await aexecute(
        CREATE_BLOCK,
        {
            "input": {
                "name": "BlockBad",
                "segments": [
                    {"analogSignals": [{"timeTrace": str(time_store.id), "samplingRate": 1.0, "tStart": 0.0, "channels": []}]}
                ],
            }
        },
    )
    assert res.errors
