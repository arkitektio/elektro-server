"""A FIELD edge: a map given by the values of an array, where the array is a node.

Rewritten from mikro's ``tests/test_field_transforms.py`` rather than ported, because what a
field *is* differs. There it is a label mask keying a table of objects. Here it is a **times
dataset**: an array whose value at sample ``i`` is the instant sample ``i`` was taken, which is
how an irregularly sampled signal and a spike train reach physical time at all. The checks on
the edge are vendored and generic, so mikro's assertions carry over; the one rule that is this
service's own is R3 -- exactly one dataset may live in a field's system -- and it is pinned here
through the API (``test_dataset_graph_smoke.py`` pins the predicate itself).

``test_clocks.py`` covers the convenience writer (``clocks.write_time_lookup``) and its unit
checks. This file goes through ``createTransformation`` and ``createCoordinateSystem``, the
doors a client actually has, and covers:

- the two shapes of lookup: a separate times dataset, and a spike train that is its own field;
- the refusals: a field nothing can be sampled from (only a lens lives there), a field with
  two candidate arrays (R3), a scalar field claiming to produce two axes, an edge that does
  not account for the axes it leaves alone, and a metric kind over an axis with no metric;
- inversion and condensation: a FIELD is walked forwards only and composes into no matrix;
- deletion: a self-field must not pin its dataset forever, and a separate field must be pinned.
"""

import pytest
from asgiref.sync import sync_to_async
from django.db.models import ProtectedError

from core import enums, models
from core.logic import graph as graph_logic
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_TRANSFORM = """
mutation Create($input: CreateTransformationInput!) {
  createTransformation(input: $input) {
    id
    kind
    invariance
    inputAxes
    outputAxes
    input { id }
    output { id }
    ... on FieldTransformation { field { id name axes { name type } residents { __typename ... on ArrayDataset { name valueUnit } } } }
  }
}
"""

CREATE_CLOCK = """
mutation ($input: CreateCoordinateSystemInput!) {
  createCoordinateSystem(input: $input) {
    id
    registrations { kind input { id } ... on FieldTransformation { field { id } } }
  }
}
"""

_SECONDS = [{"name": "t", "type": "TIME", "unit": "second"}]


async def _lookup(aexecute, input_id, output_id, field_id, input_axes=("t",), output_axes=("t",)):  # noqa: ANN001, ANN202
    transform = {"kind": "FIELD", "field": str(field_id), "inputAxes": list(input_axes), "outputAxes": list(output_axes)}
    return await aexecute(CREATE_TRANSFORM, {"input": {"input": str(input_id), "output": str(output_id), "transform": transform}})


async def _signal_times_clock(ctx):  # noqa: ANN001, ANN202
    """An irregularly sampled signal, the times dataset that times it (alone in its own system), and a clock in seconds."""
    signal = await seed.create_dataset(ctx, "Ca", seed.T_AXES, [500], value_unit="a.u.")
    times = await seed.create_dataset(ctx, "Ca/times", seed.T_AXES, [500], value_unit="second")
    clock = await seed.create_world(ctx, "session")
    return signal, times, clock


# --- the two shapes of a lookup -----------------------------------------------------------------


async def test_a_times_dataset_alone_in_its_system_is_the_field_of_a_lookup(aexecute, authenticated_context):
    """The signal's sample index is consumed, the instant is produced by the value at each sample.

    The field is a node of the graph, not a payload on the edge: it is read back as a space,
    with the dataset living in it -- which is what lets a client find the array to sample.
    """
    signal, times, clock = await _signal_times_clock(authenticated_context)

    result = await _lookup(aexecute, signal.coordinate_system_id, clock.pk, times.coordinate_system_id)
    assert not result.errors, result.errors

    edge = result.data["createTransformation"]
    assert (edge["kind"], edge["inputAxes"], edge["outputAxes"]) == ("FIELD", ["t"], ["t"])
    assert edge["invariance"] == "DIFFEOMORPHIC", "intervals between samples are not uniform, so nothing metric transfers"
    assert edge["field"]["id"] == str(times.coordinate_system_id) != edge["input"]["id"]
    assert edge["field"]["residents"] == [{"__typename": "ArrayDataset", "name": "Ca/times", "valueUnit": "second"}, {"__typename": "DataArray"}]

    stored = await models.Transformation.objects.aget(pk=edge["id"])
    assert stored.field_id == times.coordinate_system_id
    assert stored.validity == enums.PlacementValidityChoices.MANUAL.value, "an edge that arrived through the API was authored by someone"


async def test_a_spike_train_dereferences_through_its_own_values(aexecute, authenticated_context):
    """A spike train's values ARE its times: a FIELD whose `field` is the input's own system.

    mikro's label mask, over time. `spike` is consumed, `t` is produced by the value at each
    spike, and nothing passes through.
    """
    spikes = await seed.create_dataset(authenticated_context, "unit 3", seed.SPIKE_AXES, [412], value_unit="second")
    clock = await seed.create_world(authenticated_context, "session")

    result = await _lookup(aexecute, spikes.coordinate_system_id, clock.pk, spikes.coordinate_system_id, input_axes=["spike"])
    assert not result.errors, result.errors

    edge = result.data["createTransformation"]
    assert edge["kind"] == "FIELD"
    assert edge["field"]["id"] == edge["input"]["id"], "a spike train's own values are the map: field == input"


async def test_a_clock_can_be_created_with_the_lookup_that_times_a_signal(aexecute, authenticated_context):
    """`createCoordinateSystem` lowers a FIELD registration through the same writer, field and all."""
    ctx = authenticated_context
    signal = await seed.create_dataset(ctx, "Ca", seed.T_AXES, [500], value_unit="a.u.")
    times = await seed.create_dataset(ctx, "Ca/times", seed.T_AXES, [500], value_unit="second")

    registration = {"dataset": str(signal.pk), "transform": {"kind": "FIELD", "field": str(times.coordinate_system_id), "inputAxes": ["t"], "outputAxes": ["t"]}}
    result = await aexecute(CREATE_CLOCK, {"input": {"name": "session", "axes": _SECONDS, "registrations": [registration]}})
    assert not result.errors, result.errors

    (edge,) = result.data["createCoordinateSystem"]["registrations"]
    assert edge == {"kind": "FIELD", "input": {"id": str(signal.coordinate_system_id)}, "field": {"id": str(times.coordinate_system_id)}}


# --- what may be a field ------------------------------------------------------------------------


async def test_a_system_only_a_lens_lives_in_cannot_be_a_field(aexecute, authenticated_context):
    """A lens is a selection over a dataset and owns no array, so there is nothing to sample."""
    ctx = authenticated_context
    signal, times, clock = await _signal_times_clock(ctx)
    window = await seed.create_lens(ctx, times, [{"axis": "t", "start": 0, "stop": 100}])
    before = await models.Transformation.objects.acount()

    result = await _lookup(aexecute, signal.coordinate_system_id, clock.pk, window.coordinate_system_id)
    assert result.errors, "a window over the times dataset is not an array"
    message = str(result.errors[0])
    assert "Only a lens lives in coordinate system 'Ca/times/lens'" in message, message
    assert "Name the dataset's own system as the field" in message
    assert await models.Transformation.objects.acount() == before, "a refused edge must write nothing"


async def test_a_system_two_datasets_share_cannot_be_a_field(aexecute, authenticated_context):
    """Rule R3, which is this service's and not mikro's: a times dataset lives alone.

    Co-sampled datasets may share one sample grid here -- every recording of one simulation
    does -- and then "the array whose values are the map" is not a function of the system:
    two residents, two candidate lookups, and nothing on the edge to say which.
    """
    ctx = authenticated_context
    signal, times, clock = await _signal_times_clock(ctx)
    await seed.create_dataset(ctx, "Ca/times (resampled)", seed.T_AXES, [500], system=await sync_to_async(lambda: times.coordinate_system)(), value_unit="second")
    before = await models.Transformation.objects.acount()

    result = await _lookup(aexecute, signal.coordinate_system_id, clock.pk, times.coordinate_system_id)
    assert result.errors, "two datasets in the field's system are two candidate maps"
    message = str(result.errors[0])
    assert "More than one dataset lives in coordinate system 'Ca/times/intrinsic'" in message, message
    assert "lives alone in its system" in message
    assert await models.Transformation.objects.acount() == before, "a refused edge must write nothing"


async def test_an_empty_space_cannot_be_a_field(aexecute, authenticated_context):
    """A clock holds nothing, so standing in it dereferences nothing."""
    signal, _, clock = await _signal_times_clock(authenticated_context)
    other_clock = await seed.create_world(authenticated_context, "another clock")

    result = await _lookup(aexecute, signal.coordinate_system_id, clock.pk, other_clock.pk)
    assert result.errors and "No dataset lives in coordinate system" in str(result.errors[0]), str(result.errors and result.errors[0])


# --- what a field edge must say -------------------------------------------------------------------


async def test_a_field_edge_must_account_for_its_endpoints(aexecute, authenticated_context):
    """output == (input - consumed) + produced. The axes it does not consume pass through.

    A (sweep, t) signal consuming `t` and producing `t` implies (sweep, t) -- `sweep` survives
    because the edge did not name it. Claiming to produce into a bare (t) clock is then a rank
    change nothing else would catch: a FIELD has no parameters for `assert_edge_rank` to
    measure, so without this branch the edge is written and the missing `sweep` is discovered
    by whoever reads it.
    """
    ctx = authenticated_context
    sweeps = await seed.create_dataset(ctx, "sweeps", [seed.axis("sweep", enums.AxisType.INDEX), seed.axis("t", enums.AxisType.TIME)], [10, 500])
    times = await seed.create_dataset(ctx, "sweeps/times", seed.T_AXES, [500], value_unit="second")
    clock = await seed.create_world(ctx, "session")  # (t) alone

    result = await _lookup(aexecute, sweeps.coordinate_system_id, clock.pk, times.coordinate_system_id)
    assert result.errors, "(sweep,t) consuming (t) implies (sweep,t), not (t): the unconsumed sweep passes through"
    assert "pass through by name" in str(result.errors[0])


async def test_a_scalar_field_produces_exactly_one_axis(aexecute, authenticated_context):
    """No value axis means scalar, and a scalar value is one coordinate.

    The elision is deliberate -- a times dataset is a plain (t) array and giving it a length-1
    COORDINATE axis to satisfy a schema would be a phantom dimension nothing stores -- so
    the rule it implies has to be enforced instead.
    """
    ctx = authenticated_context
    spikes = await seed.create_dataset(ctx, "unit 3", seed.SPIKE_AXES, [412], value_unit="second")

    def target() -> models.CoordinateSystem:
        system = models.CoordinateSystem.objects.create(name="two-axis target", organization=ctx.request.organization)
        for index, name in enumerate(["i", "j"]):
            models.Axis.objects.create(coordinate_system=system, order=index, name=name, type=enums.AxisTypeChoices.INDEX.value)
        return system

    two_axis = await sync_to_async(target)()

    result = await _lookup(aexecute, spikes.coordinate_system_id, two_axis.pk, spikes.coordinate_system_id, input_axes=["spike"], output_axes=["i", "j"])
    assert result.errors, "a scalar array cannot produce two coordinates"
    assert "no value axis" in str(result.errors[0])


async def test_a_metric_kind_is_refused_over_an_index_space(aexecute, authenticated_context):
    """Spike 3 x 2 = spike 6 is not a wrong number, it is a meaningless one.

    ABLATION: this is exactly what the rank check waves through -- `scale: [2.0]` has one
    entry per axis, which is all `assert_edge_rank` ever asked. It is why a spike train
    reaches a clock by a lookup and never by a sampling law.
    """
    ctx = authenticated_context
    first = await seed.create_dataset(ctx, "unit 3", seed.SPIKE_AXES, [412], value_unit="second")
    second = await seed.create_dataset(ctx, "unit 4", seed.SPIKE_AXES, [412], value_unit="second")

    result = await aexecute(CREATE_TRANSFORM, {"input": {"input": str(first.coordinate_system_id), "output": str(second.coordinate_system_id), "transform": {"kind": "SCALE", "scale": [2.0]}}})
    assert result.errors, "an INDEX axis has no metric to scale"
    assert "no metric" in str(result.errors[0])


# --- inversion and condensation -------------------------------------------------------------------


async def test_a_field_is_never_walked_backwards(aexecute, authenticated_context):
    """Two spikes may share an instant and an instant between samples has no sample, so the reverse is not a function.

    The `_INVERTIBLE_KINDS` gate gives this for free, knowing nothing about time -- which is
    the evidence that a lookup really is a field and not a kind wearing a field's clothes.
    """
    signal, times, clock = await _signal_times_clock(authenticated_context)
    created = await _lookup(aexecute, signal.coordinate_system_id, clock.pk, times.coordinate_system_id)
    assert not created.errors, created.errors
    edge = await models.Transformation.objects.prefetch_related("children").aget(pk=created.data["createTransformation"]["id"])

    assert await sync_to_async(graph_logic.is_traversable)(edge) is True, "forwards, a sample has exactly one instant"
    assert await sync_to_async(graph_logic.is_reverse_traversable)(edge) is False, "backwards, it has no closed form"


async def test_a_field_places_its_input_without_condensing(aexecute, authenticated_context):
    """Reachable, and through no single matrix: the two questions every gate here asks.

    `is_placeable_in(require_affine=False)` is what `createExperiment` asks, and admits the
    signal; `require_affine=True` is what the pickers ask, and does not. The clock cannot
    reach the signal at all, because that walk would have to invert the lookup.
    """
    signal, times, clock = await _signal_times_clock(authenticated_context)
    created = await _lookup(aexecute, signal.coordinate_system_id, clock.pk, times.coordinate_system_id)
    assert not created.errors, created.errors
    edge = await models.Transformation.objects.prefetch_related("children").aget(pk=created.data["createTransformation"]["id"])
    grid = await sync_to_async(lambda: signal.coordinate_system)()

    assert await sync_to_async(graph_logic.is_condensable)(edge) is False, "a map given as an array's values has no closed form"
    assert await sync_to_async(graph_logic.is_placeable_in)(clock, grid, require_affine=False) is True
    assert await sync_to_async(graph_logic.is_placeable_in)(clock, grid, require_affine=True) is False
    assert await sync_to_async(graph_logic.is_placeable_in)(grid, clock, require_affine=False) is False, "there is no way back across a lookup"

    with pytest.raises(ValueError, match=rf"transformation {edge.pk} \(FIELD\)"):
        await sync_to_async(graph_logic.condense_path)([(edge, False)], source_axes=["t"], destination_axes=["t"])


# --- deletion -------------------------------------------------------------------------------------


async def test_dereferencing_a_mask_does_not_pin_it_forever(aexecute, authenticated_context):
    """Timing a spike train off its own values must not make the spike train undeletable.

    `field` is PROTECT, which is right for a *separate* array: deleting a times dataset's space
    would take a lookup nobody named. But a self-dereference is a fact ABOUT the dataset, and
    `input`'s CASCADE already removes it. Written as a real self-FK, PROTECT wins that race
    and the headline feature silently makes its own subject permanent.

    ABLATION: store `field=input_system` instead of null in `build_registration_edge` and
    deleting the space raises ProtectedError on its own field FK -- the self-PROTECT
    deadlock the null-means-self convention exists to avoid.
    """
    spikes = await seed.create_dataset(authenticated_context, "unit 3", seed.SPIKE_AXES, [412], value_unit="second")
    clock = await seed.create_world(authenticated_context, "session")
    grid = await sync_to_async(lambda: spikes.coordinate_system)()

    result = await _lookup(aexecute, grid.pk, clock.pk, grid.pk, input_axes=["spike"])
    assert not result.errors, result.errors
    edge_id = result.data["createTransformation"]["id"]

    # Stored as null -- the input is its own field, by definition...
    stored = await models.Transformation.objects.aget(pk=edge_id)
    assert stored.field_id is None, "a self-dereference owns no field FK"
    # ...and read back as the input, so the client never sees the convention.
    assert await sync_to_async(lambda: stored.effective_field.pk)() == grid.pk

    # The dataset moves out first: its space is PROTECTed while it lives there.
    await spikes.adelete()
    await grid.adelete()
    assert not await models.Transformation.objects.filter(pk=edge_id).aexists(), "the dereference is a fact about the dataset's space, so it goes with it"


async def test_a_separate_field_array_is_protected_from_deletion(aexecute, authenticated_context):
    """The fence: PROTECT still does its job for an array that is NOT its edge's input.

    Deleting a times dataset's space would leave a lookup claiming a map it cannot produce --
    something the caller never named. Refused, per the same rule that refuses cascading a
    shared space in use.
    """
    signal, times, clock = await _signal_times_clock(authenticated_context)
    created = await _lookup(aexecute, signal.coordinate_system_id, clock.pk, times.coordinate_system_id)
    assert not created.errors, created.errors
    times_system = await sync_to_async(lambda: times.coordinate_system)()

    # The dataset may move out; the frame its values were expressed in may not go with it.
    await times.adelete()
    with pytest.raises(ProtectedError):
        await times_system.adelete()
    assert await models.Transformation.objects.filter(pk=created.data["createTransformation"]["id"]).aexists()
