"""A guest of the organization, granted a collaboration and nothing else: what they read, and what they may draw.

Their token lists their collaborations by service instance (`collabs`, instance "1" in the test settings),
with the roles they hold in each; the guest token is minted per test. A full member ("test")
puts objects in a collaboration; what each needs to be seen comes along, and what is part of it is in it.
"""

import pytest
from asgiref.sync import sync_to_async
from authentikate import settings as authentikate_settings
from kante.context import HttpContext, UniversalRequest
from strawberry.http.temporal_response import TemporalResponse

from arkitekt_service.collaborations import items as collaboration_items
from arkitekt_service.collaborations.models import Collaboration
from core import models
from elektro_server.schema import schema
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

EXPERIMENT = "query ($id: ID!) { experiment(id: $id) { id name } }"
DATASET = "query ($id: ID!) { arrayDataset(id: $id) { id } }"
RENDER = """
query ($id: ID!) {
  experiment(id: $id) {
    id
    world { id }
    layers {
      id
      placement
      pathToWorld { transformation { id } }
      ... on TraceLayer {
        lens {
          id
          dataset {
            id
            dataArrays { id }
            anchors { valueUnit { unit } recordingSite { model { id } } simulation { model { id } } }
          }
        }
      }
    }
  }
}
"""
DRAW = """
mutation ($input: CreateAnnotationInput!) {
  createAnnotation(input: $input) { id collection { id } }
}
"""
CREATE_EXPERIMENT = "mutation ($input: CreateExperimentInput!) { createExperiment(input: $input) { id world { id } } }"
CLOCK_OFFSET = "mutation ($input: CreateClockOffsetInput!) { createClockOffset(input: $input) { id } }"
TRACE = "mutation ($input: CreateTraceLayerInput!) { createTraceLayer(input: $input) { id } }"


def _context(token: str) -> HttpContext:
    return HttpContext(request=UniversalRequest(_extensions={}), response=TemporalResponse(), headers={"Authorization": f"Bearer {token}"}, type="http")


@pytest.fixture
def guest(db, authenticated_context, settings):
    """``guest({collaboration: roles})``: a context presenting a guest's token granted those collaborations on instance "1"."""

    def mint(collaborations: dict) -> HttpContext:
        granted = {str(collaboration.pk): roles for collaboration, roles in collaborations.items()}
        settings.AUTHENTIKATE = {
            **settings.AUTHENTIKATE,
            "static_tokens": {**settings.AUTHENTIKATE["static_tokens"], "guest": {"sub": "20", "roles": [], "collabs": {"1": granted}}},
        }
        authentikate_settings.cached_settings = None
        return _context("guest")

    yield mint
    authentikate_settings.cached_settings = None


async def _run(ctx: HttpContext, query: str, **variables):
    return await schema.execute(query, context_value=ctx, variable_values=variables or None)


async def _member(query: str, **variables) -> dict:
    """Run ``query`` as the full member, as a request of its own, and hand back its data."""
    result = await _run(_context("test"), query, **variables)
    assert not result.errors, result.errors
    return result.data


async def _collaboration(ctx: HttpContext, *objects) -> Collaboration:
    """A collaboration of the organization holding ``objects``, as a full member puts them in."""

    def make() -> Collaboration:
        collaboration = Collaboration.objects.create(organization=ctx.request.organization, name="Shared")
        for obj in objects:
            collaboration_items.add(collaboration, obj)
        return collaboration

    return await sync_to_async(make)()


async def _experiment(name: str) -> models.Experiment:
    """An experiment over a minted world, empty."""
    created = await _member(CREATE_EXPERIMENT, input={"name": name})
    return await models.Experiment.objects.aget(pk=created["createExperiment"]["id"])


async def _trace(experiment: models.Experiment, chain) -> None:  # noqa: ANN001 - make_simulation_chain's namespace
    """The run's clock placed on the experiment's world at zero, and a trace of its recording."""
    await _member(CLOCK_OFFSET, input={"clock": str(chain.clock.pk), "onto": str(experiment.world_id), "offset": "0 s"})
    await _member(TRACE, input={"experiment": str(experiment.pk), "dataset": str(chain.recording.pk)})


def _refused(result, reason: str) -> None:
    assert result.errors, "it was let through"
    assert result.errors[0].extensions.get("reason") == reason, result.errors


async def test_a_guest_reads_the_experiment_in_their_collaboration_and_nothing_else(authenticated_context, guest):
    shared = await _experiment("Shared")
    other = await _experiment("Other")  # the newest: first in the default ordering
    ctx = guest({await _collaboration(authenticated_context, shared): []})

    listed = await _run(ctx, "{ experiments { id } }")
    assert not listed.errors, listed.errors
    assert [e["id"] for e in listed.data["experiments"]] == [str(shared.pk)]
    # Narrowed in the query, not only dropped afterwards: the first page is the shared one.
    paged = await _run(ctx, "{ experiments(pagination: {limit: 1}) { id } }")
    assert [e["id"] for e in paged.data["experiments"]] == [str(shared.pk)]
    assert (await _run(ctx, EXPERIMENT, id=str(shared.pk))).data["experiment"]["name"] == "Shared"
    assert (await _run(ctx, EXPERIMENT, id=str(other.pk))).errors


async def test_an_experiment_in_a_collaboration_renders_for_a_guest(authenticated_context, guest, make_simulation_chain):
    chain = await make_simulation_chain()
    experiment = await _experiment("Paired pulse")
    await _trace(experiment, chain)
    ctx = guest({await _collaboration(authenticated_context, experiment): []})

    result = await _run(ctx, RENDER, id=str(experiment.pk))
    assert not result.errors, result.errors
    rendered = result.data["experiment"]
    assert rendered["world"]["id"] == str(experiment.world_id)
    (layer,) = rendered["layers"]
    assert layer["placement"] == "PLACED"
    assert len(layer["pathToWorld"]) == 2, "the sampling law onto the run's clock, and the clock's offset onto the world: the edges come along with the spaces they leave"
    dataset = layer["lens"]["dataset"]
    assert dataset["id"] == str(chain.recording.pk)
    assert dataset["dataArrays"]
    (anchor,) = dataset["anchors"]
    assert anchor["valueUnit"]["unit"] == "mV"
    assert anchor["recordingSite"]["model"]["id"] == anchor["simulation"]["model"]["id"] == str(chain.neuron_model.pk), "a run brings the model it simulated"


async def test_a_layer_added_later_brings_what_it_draws(authenticated_context, guest, make_simulation_chain):
    chain = await make_simulation_chain()
    experiment = await _experiment("Growing")
    ctx = guest({await _collaboration(authenticated_context, experiment): []})
    await _trace(experiment, chain)

    result = await _run(ctx, RENDER, id=str(experiment.pk))
    assert not result.errors, result.errors
    (layer,) = result.data["experiment"]["layers"]
    assert layer["lens"]["dataset"]["id"] == str(chain.recording.pk)
    assert len(layer["pathToWorld"]) == 2


async def test_an_edge_out_of_a_shared_space_authored_later_comes_along(authenticated_context, guest, make_simulation_chain):
    chain = await make_simulation_chain()
    session = await seed.create_clock(authenticated_context, "session")
    elsewhere = await seed.create_clock(authenticated_context, "elsewhere")
    ctx = guest({await _collaboration(authenticated_context, chain.recording): []})

    # The run's clock is in the collaboration (the recording's grid leads to it); the elsewhere clock is not.
    synced = await _member(CLOCK_OFFSET, input={"clock": str(chain.clock.pk), "onto": str(session.pk), "offset": "2 s"})
    unrelated = await _member(CLOCK_OFFSET, input={"clock": str(elsewhere.pk), "onto": str(session.pk), "offset": "1 s"})

    edge = "query ($id: ID!) { transformation(id: $id) { id output { id } } }"
    seen = await _run(ctx, edge, id=synced["createClockOffset"]["id"])
    assert not seen.errors, seen.errors
    assert seen.data["transformation"]["output"]["id"] == str(session.pk), "with the space it leads to"
    assert (await _run(ctx, edge, id=unrelated["createClockOffset"]["id"])).errors, "an edge into that space from elsewhere is someone else's"


async def test_what_is_in_no_collaboration_is_left_out(authenticated_context, guest, make_simulation_chain):
    chain = await make_simulation_chain()
    experiment = await _experiment("Shared")
    await _trace(experiment, chain)
    ctx = guest({await _collaboration(authenticated_context, experiment): []})

    assert (await _run(ctx, DATASET, id=str(chain.stimulus.pk))).errors, "the run's other output is not drawn in the experiment"
    seen = await _run(ctx, DATASET, id=str(chain.recording.pk))
    assert seen.data["arrayDataset"]["id"] == str(chain.recording.pk)  # brought by the experiment
    # Root fields that hand out values computed from many rows are closed to guests.
    lineage = await _run(ctx, "query ($id: ID!) { lineageGraph(coordinateSystem: $id) { __typename } }", id=str(chain.grid.pk))
    _refused(lineage, "COLLABORATION_DOES_NOT_REACH")


async def test_a_shared_neuron_model_shows_none_of_the_runs_that_simulate_it(authenticated_context, guest, make_simulation_chain):
    chain = await make_simulation_chain()
    sibling = await models.NeuronModel.objects.acreate(name="Sibling", hash="sibling", environment_id=chain.neuron_model.environment_id, organization=authenticated_context.request.organization)
    ctx = guest({await _collaboration(authenticated_context, chain.neuron_model): []})

    shared = await _run(ctx, "{ neuronModels { id } modEnvironments { id mechanisms { id } } arrayDatasets { id } coordinateAnchors { id } }")
    assert not shared.errors, shared.errors
    assert [m["id"] for m in shared.data["neuronModels"]] == [str(chain.neuron_model.pk)], f"not the sibling {sibling.pk} on the same mod environment"
    assert [e["id"] for e in shared.data["modEnvironments"]] == [str(chain.neuron_model.environment_id)], "the environment it is simulated with comes along"
    assert shared.data["arrayDatasets"] == [] and shared.data["coordinateAnchors"] == [], "a run's sites and state are its dataset's, not the model's"


async def test_an_editor_in_the_collaboration_draws_there_and_only_there(authenticated_context, guest, make_simulation_chain):
    chain = await make_simulation_chain()
    canvas = await _experiment("Canvas")
    await _trace(canvas, chain)
    other = await _experiment("Other")
    ctx = guest({await _collaboration(authenticated_context, canvas): ["editor"]})

    drawn = await _run(ctx, DRAW, input={"experiment": str(canvas.pk), "kind": "EVENT", "name": "pulse", "vectors": [[0.002]]})
    assert not drawn.errors, drawn.errors
    collection = drawn.data["createAnnotation"]["collection"]["id"]
    again = await _run(ctx, DRAW, input={"collection": collection, "kind": "EVENT", "name": "pulse 2", "vectors": [[0.004]]})
    assert not again.errors, again.errors
    listed = await _run(ctx, "{ annotations { id } }")
    assert len(listed.data["annotations"]) == 2, "what they drew is in the collaboration, as part of the collection minted for the experiment"
    surface = await _run(ctx, "query ($id: ID!) { experiment(id: $id) { annotationCollection { id coordinateSystem { id } } layers { kind pathToWorld { transformation { id } } } } }", id=str(canvas.pk))
    assert not surface.errors, surface.errors
    assert surface.data["experiment"]["annotationCollection"]["id"] == collection
    (drawing,) = [layer for layer in surface.data["experiment"]["layers"] if layer["kind"] == "ANNOTATION"]
    assert len(drawing["pathToWorld"]) == 1, "the drawing surface's identity registration into the world"

    _refused(await _run(ctx, DRAW, input={"experiment": str(other.pk), "kind": "EVENT", "vectors": [[0.002]]}), "SHARE_INSUFFICIENT")
    assert await models.Annotation.objects.acount() == 2


async def test_a_viewer_draws_nothing_and_no_guest_does_anything_else(authenticated_context, guest):
    canvas = await _experiment("Canvas")
    collaboration = await _collaboration(authenticated_context, canvas)

    _refused(await _run(guest({collaboration: []}), DRAW, input={"experiment": str(canvas.pk), "kind": "EVENT", "vectors": [[0.002]]}), "SHARE_INSUFFICIENT")
    deleted = await _run(guest({collaboration: ["editor"]}), "mutation ($input: DeleteInput!) { deleteExperiment(input: $input) }", input={"id": str(canvas.pk)})
    _refused(deleted, "SCOPED_READ_ONLY")
    assert await models.Experiment.objects.filter(pk=canvas.pk).aexists()
    assert await models.Annotation.objects.acount() == 0


async def test_a_member_puts_an_experiment_in_a_collaboration_and_takes_it_out(authenticated_context, guest):
    experiment = await _experiment("Handed over")
    created = await _member("mutation { createCollaboration(input: {name: \"Review\"}) { id } }")
    collaboration = created["createCollaboration"]["id"]
    target = {"collaboration": collaboration, "identifier": "@elektro/experiment", "object": str(experiment.pk)}

    added = await _member("mutation ($input: CollaborationObjectInput!) { addToCollaboration(input: $input) { items { identifier brought } } }", input=target)
    items = added["addToCollaboration"]["items"]
    assert {"identifier": "@elektro/experiment", "brought": False} in items
    assert any(item["brought"] for item in items), "its world came along"
    ctx = guest({await Collaboration.objects.aget(pk=collaboration): []})
    assert (await _run(ctx, EXPERIMENT, id=str(experiment.pk))).data["experiment"]["name"] == "Handed over"

    await _member("mutation ($input: CollaborationObjectInput!) { removeFromCollaboration(input: $input) { id } }", input=target)
    assert (await _run(ctx, EXPERIMENT, id=str(experiment.pk))).errors


def _type_line(sdl: str, name: str) -> str:
    return next(line for line in sdl.splitlines() if line.startswith(f"type {name} "))


async def test_the_schema_says_what_each_type_is_and_who_may_draw():
    sdl = str(schema)
    assert '@identified(by: "@elektro/experiment")' in _type_line(sdl, "Experiment")
    create = next(line.strip() for line in sdl.splitlines() if line.strip().startswith("createAnnotation("))
    assert create.endswith("@auth(allow_scoped: true)"), create


async def test_an_anchor_and_a_run_hung_on_a_shared_dataset_later_come_along(authenticated_context, guest, make_simulation_chain):
    chain = await make_simulation_chain()
    ctx = guest({await _collaboration(authenticated_context, chain.recording): []})

    def hang() -> models.NeuronModel:
        rerun = models.NeuronModel.objects.create(name="Rerun", hash="rerun", environment=chain.neuron_model.environment, organization=chain.recording.organization)
        anchor = models.CoordinateAnchor.objects.create(dataset=chain.recording, coordinates={"t": 5})
        models.ChannelLabel.objects.create(anchor=anchor, label="soma")
        models.SimulationState.objects.create(anchor=anchor, model=rerun, duration=40_000_000_000)
        return rerun

    rerun = await sync_to_async(hang)()
    result = await _run(ctx, "query ($id: ID!) { arrayDataset(id: $id) { anchors { channelLabel { label } simulation { model { id } } } } }", id=str(chain.recording.pk))
    assert not result.errors, result.errors
    hung = [anchor for anchor in result.data["arrayDataset"]["anchors"] if anchor["channelLabel"] is not None]
    assert hung == [{"channelLabel": {"label": "soma"}, "simulation": {"model": {"id": str(rerun.pk)}}}]
