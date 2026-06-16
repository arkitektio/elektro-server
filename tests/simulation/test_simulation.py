"""createSimulation executed against the schema (NeuronModel + a Zarr time-trace
store seeded in MinIO)."""

import pytest

from core.models import Simulation

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_SIMULATION = """
mutation ($input: CreateSimulationInput!) {
  createSimulation(input: $input) { id name }
}
"""


async def test_create_simulation(aexecute, make_neuron_model, zarr_store):
    nm = await make_neuron_model()
    store = await zarr_store()  # seeded zarr.json
    res = await aexecute(
        CREATE_SIMULATION,
        {
            "input": {
                "name": "Sim",
                "model": str(nm.id),
                "timeTrace": str(store.id),
                "duration": 400,
                "recordings": [],
                "stimuli": [],
            }
        },
    )
    assert not res.errors, res.errors
    assert res.data["createSimulation"]["name"] == "Sim"
    assert await Simulation.objects.filter(name="Sim").aexists()


# --- negatives ---------------------------------------------------------------


async def test_create_simulation_missing_zarr_metadata(aexecute, make_neuron_model, zarr_store):
    nm = await make_neuron_model()
    store = await zarr_store(seed=False)  # no zarr.json -> fill_info raises FileNotFoundError
    res = await aexecute(
        CREATE_SIMULATION,
        {
            "input": {
                "name": "SimBad",
                "model": str(nm.id),
                "timeTrace": str(store.id),
                "duration": 400,
                "recordings": [],
                "stimuli": [],
            }
        },
    )
    assert res.errors


async def test_create_simulation_unknown_model(aexecute, zarr_store):
    store = await zarr_store()
    res = await aexecute(
        CREATE_SIMULATION,
        {
            "input": {
                "name": "SimNoModel",
                "model": "999999",
                "timeTrace": str(store.id),
                "duration": 400,
                "recordings": [],
                "stimuli": [],
            }
        },
    )
    assert res.errors
