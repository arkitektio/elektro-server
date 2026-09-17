"""createExperiment executed against the schema: recordings and stimuli, laid out on one timeline.

An experiment is mikro's scene, over time. It holds no time facts of its own: where a
recording sits is one edge from its simulation's clock into the experiment's world, and how
much of it is shown is a lens. These tests state things the way a client does -- "this
recording, 50 ms in, the first 10 ms of it" -- and check what that was written as, and that
the placement read back is the one that was stated.
"""

import pytest
from asgiref.sync import sync_to_async
from pytest import approx

from core.models import CoordinateSystem, Experiment, Lens, Transformation

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


VIEW_FIELDS = """
    id
    label
    order
    visible
    offset
    duration
    placement
    placementValidity
    placementInvariance
    lens { id shape slices { axis start stop } }
    pathToWorld { inverted transformation { kind input { name } output { name } } }
"""

CREATE_EXPERIMENT = """
mutation ($input: CreateExperimentInput!) {
  createExperiment(input: $input) {
    id
    name
    description
    pinned
    world { id name epoch axes { name type unit } registrations { kind input { name } } }
    recordingViews { %s recording { id } asAffine { matrix inputAxes outputAxes total } }
    stimulusViews { %s stimulus { id } }
  }
}
""" % (VIEW_FIELDS, VIEW_FIELDS)

AS_AFFINE = """
query ($id: ID!) { experiment(id: $id) { recordingViews { asAffine { matrix } } } }
"""


async def test_create_experiment(aexecute, make_simulation_chain):
    """A run recorded at 10 kHz, laid 50 ms into a fresh timeline: t_world = sample * 0.0001 s + 0.05 s."""
    chain = await make_simulation_chain()
    views = {"recordingViews": [{"recording": str(chain.recording.id), "offset": "50 ms", "label": "Vm"}], "stimulusViews": [{"stimulus": str(chain.stimulus.id), "offset": "50 ms"}]}
    res = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Exp", **views}})
    assert not res.errors, res.errors
    experiment = res.data["createExperiment"]

    assert experiment["name"] == "Exp"
    assert experiment["world"]["name"] == "Exp/world"
    assert experiment["world"]["axes"] == [{"name": "t", "type": "TIME", "unit": "second"}]
    assert experiment["world"]["epoch"] is None, "trial-aligned time has no wall clock"
    assert experiment["world"]["registrations"] == [{"kind": "BY_DIMENSION", "input": {"name": "sim/clock"}}], "two views of one run, one edge: they cannot be laid out apart"

    (recording_view,), (stimulus_view,) = experiment["recordingViews"], experiment["stimulusViews"]
    assert (recording_view["label"], recording_view["order"], stimulus_view["order"]) == ("Vm", 0, 1)
    assert recording_view["offset"] == stimulus_view["offset"] == "50 ms", "derived from the one edge, so they agree by construction"
    assert recording_view["duration"] == "40 ms", "400 samples at 10 kHz"
    assert recording_view["lens"]["slices"] == [] and recording_view["lens"]["shape"] == [400]

    assert (recording_view["placement"], recording_view["placementValidity"], recording_view["placementInvariance"]) == ("PLACED", "INFERRED", "AFFINE")
    hops = [(step["transformation"]["input"]["name"], step["transformation"]["output"]["name"]) for step in recording_view["pathToWorld"]]
    assert hops == [("sim/soma.v/intrinsic", "sim/clock"), ("sim/clock", "Exp/world")], "sample grid -> simulation clock -> world"
    assert all(step["inverted"] is False for step in recording_view["pathToWorld"])

    affine = recording_view["asAffine"]
    assert (affine["inputAxes"], affine["outputAxes"], affine["total"]) == (["t"], ["t"], True)
    assert affine["matrix"][0] == approx([0.0001, 0.05]), "the sampling law in ms and the offset in s, multiplied out into seconds"

    assert await Experiment.objects.filter(name="Exp").aexists()
    assert not [field.name for field in Experiment._meta.get_fields() if field.name == "time_dataset"]


async def test_a_window_is_lowered_to_a_lens_in_sample_indices(aexecute, make_simulation_chain):
    """The 10 ms from 5 ms in, of a run recorded at 10 kHz from t = 0: samples 50 to 150."""
    chain = await make_simulation_chain()
    view = {"recording": str(chain.recording.id), "offset": "0 s", "window": {"start": "5 ms", "stop": "15 ms"}}
    res = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Windowed", "recordingViews": [view]}})
    assert not res.errors, res.errors
    (recording_view,) = res.data["createExperiment"]["recordingViews"]

    assert recording_view["lens"]["slices"] == [{"axis": "t", "start": 50, "stop": 150}]
    assert recording_view["lens"]["shape"] == [100]
    assert recording_view["duration"] == "10 ms"
    assert [step["transformation"]["kind"] for step in recording_view["pathToWorld"]] == ["TRANSLATION", "BY_DIMENSION", "BY_DIMENSION"], "lens shift, sampling law, offset"
    assert recording_view["asAffine"]["matrix"][0] == approx([0.0001, 0.005]), "sample 0 of the window is sample 50 of the run, 5 ms in"


async def test_showing_everything_reuses_the_unsliced_lens(aexecute, make_simulation_chain):
    chain = await make_simulation_chain()
    for name in ("First", "Second"):
        res = await aexecute(CREATE_EXPERIMENT, {"input": {"name": name, "recordingViews": [{"recording": str(chain.recording.id), "offset": "0 s"}]}})
        assert not res.errors, res.errors
    assert await Lens.objects.filter(dataset=chain.recording.dataset_id).acount() == 1, "an unsliced lens owns no space, so a second would say nothing the first did not"


async def test_refining_the_offset_moves_every_view_that_looks_through_it(aexecute, make_simulation_chain):
    """Nothing stored a composed path, so there is nothing to go stale."""
    chain = await make_simulation_chain()
    created = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Movable", "recordingViews": [{"recording": str(chain.recording.id), "offset": "50 ms"}]}})
    experiment = created.data["createExperiment"]
    edge = await sync_to_async(lambda: Transformation.objects.get(input=chain.clock, output_id=experiment["world"]["id"], parent__isnull=True))()

    update = "mutation ($input: UpdateTransformationInput!) { updateTransformation(input: $input) { id } }"
    moved = await aexecute(update, {"input": {"id": str(edge.pk), "affine": [[0.001, 2.0]]}})
    assert not moved.errors, moved.errors

    reread = await aexecute(AS_AFFINE, {"id": experiment["id"]})
    assert reread.data["experiment"]["recordingViews"][0]["asAffine"]["matrix"][0] == approx([0.0001, 2.0])


async def test_an_experiment_can_adopt_a_world_it_does_not_own(aexecute, authenticated_context, make_simulation_chain):
    """Two experiments over one world: the second needs no offset, because the clock is already there."""
    from tests import seed

    chain = await make_simulation_chain()
    world = await seed.create_world(authenticated_context, "shared timeline")
    first = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "A", "world": str(world.pk), "recordingViews": [{"recording": str(chain.recording.id), "offset": "1 s"}]}})
    assert not first.errors, first.errors
    second = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "B", "world": str(world.pk), "stimulusViews": [{"stimulus": str(chain.stimulus.id)}]}})
    assert not second.errors, second.errors

    assert second.data["createExperiment"]["world"]["id"] == str(world.pk)
    assert second.data["createExperiment"]["stimulusViews"][0]["offset"] == "1 s", "the offset is the world's fact, not either experiment's"
    assert await Transformation.objects.filter(output=world, parent__isnull=True).acount() == 1

    # Deleting an experiment never deletes the space it adopted.
    deleted = await aexecute("mutation ($input: DeleteInput!) { deleteExperiment(input: $input) }", {"input": {"id": first.data["createExperiment"]["id"]}})
    assert not deleted.errors, deleted.errors
    assert await CoordinateSystem.objects.filter(pk=world.pk).aexists()


# --- a run timed by a lookup: admitted, and honest about having no matrix ------------------------


async def test_a_view_over_a_lookup_timed_run_is_placed_without_an_affine_map(aexecute, make_simulation_chain):
    """Deliberately looser than mikro's gate (rfc10), which refuses a layer that does not condense: a timeline can draw samples at looked-up instants."""
    chain = await make_simulation_chain(timing="lookup")
    res = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "CVode", "recordingViews": [{"recording": str(chain.recording.id), "offset": "0 s"}]}})
    assert res.data is not None and res.data["createExperiment"]["recordingViews"][0]["placement"] == "PLACED"
    (recording_view,) = res.data["createExperiment"]["recordingViews"]
    assert recording_view["placementInvariance"] == "DIFFEOMORPHIC", "intervals between samples are not uniform, so nothing metric transfers"
    assert [step["transformation"]["kind"] for step in recording_view["pathToWorld"]] == ["FIELD", "BY_DIMENSION"]
    assert recording_view["duration"] is None, "a sample count is not a duration without a sampling law"

    assert res.errors and "asAffine" in str(res.errors[0].path), "the map has no closed form, and says so rather than answering null"


async def test_a_window_over_a_lookup_timed_run_is_refused(aexecute, make_simulation_chain):
    chain = await make_simulation_chain(timing="lookup")
    view = {"recording": str(chain.recording.id), "offset": "0 s", "window": {"start": "5 ms", "stop": "15 ms"}}
    res = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "NoInverse", "recordingViews": [view]}})
    assert res.errors and "has no closed-form inverse" in str(res.errors[0])
    assert not await Experiment.objects.filter(name="NoInverse").aexists()


# --- negatives ---------------------------------------------------------------


async def test_two_views_of_one_run_cannot_state_two_offsets(aexecute, make_simulation_chain):
    """The bug the per-view offset column allowed: stimulus and response silently laid out apart."""
    chain = await make_simulation_chain()
    views = {"recordingViews": [{"recording": str(chain.recording.id), "offset": "50 ms"}], "stimulusViews": [{"stimulus": str(chain.stimulus.id), "offset": "60 ms"}]}
    res = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Misaligned", **views}})
    assert res.errors and "state different offsets" in str(res.errors[0])
    assert not await Experiment.objects.filter(name="Misaligned").aexists()
    assert not await CoordinateSystem.objects.filter(name="Misaligned/world").aexists(), "refused inside the transaction"


async def test_a_view_with_no_route_into_the_world_is_refused(aexecute, make_simulation_chain):
    """Nothing is placed by default: an assumed offset of zero cannot be told from a measured one."""
    chain = await make_simulation_chain()
    res = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Floating", "recordingViews": [{"recording": str(chain.recording.id)}]}})
    assert res.errors and "Nothing relates" in str(res.errors[0]) and "State its `offset`" in str(res.errors[0])


async def test_create_experiment_unknown_stimulus(aexecute):
    res = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "ExpBad", "stimulusViews": [{"stimulus": "999999"}]}})
    assert res.errors


async def test_create_experiment_missing_name(aexecute):
    res = await aexecute(CREATE_EXPERIMENT, {"input": {"stimulusViews": [], "recordingViews": []}})
    assert res.errors


async def test_a_view_shows_a_window_or_a_lens_but_not_both(aexecute, make_simulation_chain):
    chain = await make_simulation_chain()
    view = {"recording": str(chain.recording.id), "offset": "0 s", "window": {"stop": "5 ms"}, "lens": "1"}
    res = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Both", "recordingViews": [view]}})
    assert res.errors and "A view shows one selection" in str(res.errors[0])


async def test_another_organization_cannot_lay_out_this_ones_recordings_or_adopt_its_world(aexecute, authenticated_context, make_simulation_chain, other_org_context):
    from tests import seed

    chain = await make_simulation_chain()
    world = await seed.create_world(authenticated_context, "mine")

    stolen = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Theirs", "recordingViews": [{"recording": str(chain.recording.id), "offset": "0 s"}]}}, context=other_org_context)
    assert stolen.errors
    adopted = await aexecute(CREATE_EXPERIMENT, {"input": {"name": "Squatter", "world": str(world.pk)}}, context=other_org_context)
    assert adopted.errors
    assert not await Experiment.objects.filter(name__in=["Theirs", "Squatter"]).aexists()
