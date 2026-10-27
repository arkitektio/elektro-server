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
from django.core.management import call_command
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
        # Seeded with no value unit, and derived from nothing.
        "@elektro/value_dimension": "",
        "@elektro/value_kind": "continuous",
    }
    assert result.data["arrayDataset"]["descriptors"] == whole
    assert {"id": str(dataset.pk), "descriptors": whole} in result.data["arrayDatasets"]
    # The lens keeps every axis of its dataset and narrows the channel axis to one.
    assert result.data["lens"]["descriptors"] == {**whole, "@elektro/n_channels": 1}
    # A structure that declares no descriptors has none.
    assert result.data["folder"]["descriptors"] == {}

    declared = {s["identifier"]: [d["key"] for d in s["descriptors"]] for s in service.manifest()["structures"]}
    # Every declared key is computed and stored, what the values are included.
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
    assert await sync_to_async(reembed_stale)(organization=authenticated_context.request.organization.identifier) == {"reembedded": 1}

    assert (await models.TableDataset.objects.aget(pk=mine.pk)).embedding_model == engine.model_id()
    assert (await models.TableDataset.objects.aget(pk=theirs.pk)).embedding_model == "another-model"
    # Theirs is still there for their own agent's run.
    assert await sync_to_async(reembed_stale)(organization=other_org_context.request.organization.identifier) == {"reembedded": 1}
    assert (await models.TableDataset.objects.aget(pk=theirs.pk)).embedding_model == engine.model_id()


REQUIRED = "query Required($requires: [DescriptorConstraintInput!]!) { arrayDatasets(filters: {requires: $requires}) { id } lenses(filters: {requires: $requires}) { id dataset { id } } }"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_port_asks_for_what_the_values_measure(aexecute, create_array_dataset):
    """What a voltage port asks: the dimension of the dataset-wide value unit, stored when the anchor stating it is written."""
    voltage = await create_array_dataset("membrane potential", [1000, 4], value_unit="mV")
    current = await create_array_dataset("holding current", [1000, 4], value_unit="pA")

    async def required(requires: list[dict]) -> tuple[set[str], set[str]]:
        result = await aexecute(REQUIRED, {"requires": requires})
        assert not result.errors, result.errors
        return {row["id"] for row in result.data["arrayDatasets"]}, {row["dataset"]["id"] for row in result.data["lenses"]}

    datasets, _ = await required([{"key": "@elektro/value_dimension", "operator": "EQUALS", "value": "voltage"}])
    assert datasets == {voltage["id"]}
    datasets, _ = await required([{"key": "@elektro/value_dimension", "operator": "IN", "value": ["voltage", "current"]}, {"key": "@elektro/n_channels", "operator": "EQUALS", "value": 4}])
    assert datasets == {voltage["id"], current["id"]}

    # A lens is what its dataset's values are; restating the unit restores both.
    lens = await sync_to_async(lambda: models.Lens.objects.create(dataset_id=voltage["id"], coordinate_system_id=models.ArrayDataset.objects.get(pk=voltage["id"]).coordinate_system_id, slices=[]))()
    _, lens_datasets = await required([{"key": "@elektro/value_dimension", "operator": "EQUALS", "value": "voltage"}])
    assert lens_datasets == {voltage["id"]}
    unit = await models.ValueUnit.objects.aget(anchor__dataset_id=voltage["id"], anchor__coordinates={})
    unit.unit = "nA"
    await unit.asave()
    datasets, lens_datasets = await required([{"key": "@elektro/value_dimension", "operator": "EQUALS", "value": "current"}])
    assert datasets == {voltage["id"], current["id"]} and lens_datasets == {voltage["id"]}
    assert (await models.Lens.objects.aget(pk=lens.pk)).stored_descriptors["@elektro/value_dimension"] == "current"

    result = await aexecute(REQUIRED, {"requires": [{"key": "@elektro/colour", "operator": "EQUALS", "value": "red"}]})
    assert result.errors and "not a descriptor here" in result.errors[0].message


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_setup_job_gives_a_row_what_it_owes(create_array_dataset):
    made = await create_array_dataset("old recording", [1000, 4], value_unit="mV")
    expected = (await models.ArrayDataset.objects.aget(pk=made["id"])).stored_descriptors
    assert expected["@elektro/value_dimension"] == "voltage"
    await models.ArrayDataset.objects.filter(pk=made["id"]).aupdate(stored_descriptors={})
    await sync_to_async(call_command)("restore_descriptors")
    assert (await models.ArrayDataset.objects.aget(pk=made["id"])).stored_descriptors == expected
