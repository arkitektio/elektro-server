"""``descriptors`` on elektro's types: what an object says about itself, from its structure's declaration.

One declaration (``elektro_server.service``) feeds the manifest, the signals and this field, so the
tests hold the three to each other: the field answers what a signal about the object carries, in
the keys the manifest declares. And the agent's sweep does one organization's share of the work.
"""

import time

import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models
from elektro_server.hook_agent import agent
from elektro_server.service import service
from embeddings import engine
from tests import seed
from tests.test_signals import intake  # noqa: F401  the fixture

DESCRIBED = """
    query Described($dataset: ID!, $lens: ID!, $folder: ID!) {
        arrayDataset(id: $dataset) { descriptors }
        lens(id: $lens) { descriptors }
        folder(id: $folder) { descriptors }
        arrayDatasets { id descriptors }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_object_answers_the_descriptors_its_structure_declares(aexecute, authenticated_context: HttpContext):
    dataset = await seed.create_array_dataset(authenticated_context, "recording", axes=seed.TC_AXES, shapes=[[1000, 4]])
    lens = await seed.create_lens(authenticated_context, dataset, slices=[{"axis": "c", "start": 0, "stop": 1}])
    folder = await seed.create_folder(authenticated_context, "shelf")

    result = await aexecute(DESCRIBED, {"dataset": str(dataset.pk), "lens": str(lens.pk), "folder": str(folder.pk)})
    assert not result.errors, result.errors

    whole = {
        "@elektro/n_space_axes": 0,
        "@elektro/n_time_axes": 1,
        "@elektro/n_channel_axes": 1,
        "@elektro/n_frequency_axes": 0,
        "@elektro/n_index_axes": 0,
        "@elektro/n_channels": 4,
        "@elektro/n_samples": 1000,
        "@elektro/n_indices": 0,
    }
    assert result.data["arrayDataset"]["descriptors"] == whole
    assert {"id": str(dataset.pk), "descriptors": whole} in result.data["arrayDatasets"]
    # The lens keeps every axis of its dataset and narrows the channel axis to one.
    assert result.data["lens"]["descriptors"] == {**whole, "@elektro/n_channels": 1}
    # A structure that declares no descriptors has none.
    assert result.data["folder"]["descriptors"] == {}

    declared = {s["identifier"]: [d["key"] for d in s["descriptors"]] for s in service.manifest()["structures"]}
    assert set(result.data["arrayDataset"]["descriptors"]) == set(declared["@elektro/arraydataset"])
    assert set(result.data["lens"]["descriptors"]) == set(declared["@elektro/lens"])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_field_answers_what_the_signal_carried(intake, aexecute, create_array_dataset):  # noqa: F811
    # Through ``createArrayDataset``: one transaction, so the signal is described at its commit, axes and levels written.
    dataset = await create_array_dataset("signalled recording", [1000, 4])

    def created_signals() -> list[dict]:
        # Each signal is posted from its own thread: wait for the CREATED one, whichever arrives first.
        deadline = time.monotonic() + 10
        while True:
            found = [r["json"] for r in list(intake.received) if (r["json"]["identifier"], r["json"]["kind"], r["json"]["object"]) == ("@elektro/arraydataset", "CREATED", dataset["id"])]
            if found or time.monotonic() > deadline:
                return found
            time.sleep(0.05)

    created = await sync_to_async(created_signals)()
    assert len(created) == 1
    result = await aexecute("query Dataset($id: ID!) { arrayDataset(id: $id) { descriptors } }", {"id": dataset["id"]})
    assert not result.errors, result.errors
    assert result.data["arrayDataset"]["descriptors"] == created[0]["descriptors"]
    assert created[0]["descriptors"]["@elektro/n_samples"] == 1000


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_sweep_for_one_organization_claims_only_its_rows(authenticated_context: HttpContext, other_org_context: HttpContext):
    """Every organization has the agent and its own schedule: a run must not do another's work."""
    mine = await seed.create_table_dataset(authenticated_context, "mine")
    theirs = await seed.create_table_dataset(other_org_context, "theirs")
    await models.TableDataset.objects.filter(pk__in=[mine.pk, theirs.pk]).aupdate(embedding=None, embedding_model="another-model")

    reembed_stale = agent.actions["reembed_stale"].function
    assert await sync_to_async(reembed_stale)(organization=authenticated_context.request.organization.slug) == {"reembedded": 1}

    assert (await models.TableDataset.objects.aget(pk=mine.pk)).embedding_model == engine.model_id()
    assert (await models.TableDataset.objects.aget(pk=theirs.pk)).embedding_model == "another-model"
    # Theirs is still there for their own agent's run.
    assert await sync_to_async(reembed_stale)(organization=other_org_context.request.organization.slug) == {"reembedded": 1}
    assert (await models.TableDataset.objects.aget(pk=theirs.pk)).embedding_model == engine.model_id()
