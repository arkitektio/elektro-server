"""createExperiment executed against the schema (needs a Trace + Stimulus +
Recording, built directly via the simulation-chain factory)."""

import pytest

from core.models import Experiment

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_EXPERIMENT = """
mutation ($input: CreateExperimentInput!) {
  createExperiment(input: $input) { id name }
}
"""


async def test_create_experiment(aexecute, make_simulation_chain):
    chain = await make_simulation_chain()
    res = await aexecute(
        CREATE_EXPERIMENT,
        {
            "input": {
                "name": "Exp",
                "timeTrace": str(chain.time_trace.id),
                "stimulusViews": [{"stimulus": str(chain.stimulus.id)}],
                "recordingViews": [{"recording": str(chain.recording.id)}],
            }
        },
    )
    assert not res.errors, res.errors
    assert res.data["createExperiment"]["name"] == "Exp"
    assert await Experiment.objects.filter(name="Exp").aexists()


async def test_create_experiment_unknown_stimulus(aexecute, make_simulation_chain):
    chain = await make_simulation_chain()
    res = await aexecute(
        CREATE_EXPERIMENT,
        {
            "input": {
                "name": "ExpBad",
                "timeTrace": str(chain.time_trace.id),
                "stimulusViews": [{"stimulus": "999999"}],
                "recordingViews": [],
            }
        },
    )
    assert res.errors


async def test_create_experiment_missing_name(aexecute):
    res = await aexecute(
        CREATE_EXPERIMENT, {"input": {"stimulusViews": [], "recordingViews": []}}
    )
    assert res.errors
