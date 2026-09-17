"""Clocks, and the edges that put samples onto them.

This module is elektro's own; the graph it writes into is vendored from mikro. In mikro,
physical space enters the model exactly once: an ordinary unit-carrying system plus one
edge from a dataset's pixel grid. Here that system is a **clock** -- one TIME axis carrying
a time unit -- and the edge is how a dataset's samples are timed. There are three such edges,
and between them they replace every time column this service used to keep:

**The sampling law** (:func:`write_sampling_law`): a regularly sampled dataset maps onto its
clock as ``t = sample * period + t_start``. *One* edge -- a ``BY_DIMENSION`` over the time
axis carrying a 1x2 affine -- never a SCALE edge beside a TRANSLATION edge: two edges
between the same two spaces are *rivals* the path search chooses between, not a
composition. A ``BY_DIMENSION`` even for a one-axis dataset, so a ``(t)`` and a ``(t, c)``
dataset read identically, and because it is the honest statement for the second: the law
says nothing about ``c``, where a rank-changing AFFINE would say "times zero". It replaces
``AnalogSignal.sampling_rate``, ``.t_start`` and the redundant ``.time_dataset`` -- which was
a second copy of the same fact, free to disagree with the first.

**The time lookup** (:func:`write_time_lookup`): an irregularly sampled signal and a spike
train have no law, only a list of instants. That is a ``FIELD``: a map given by the values
of an array. For an irregular signal the array is a separate times dataset, alone in its own
system (rule R3); for a spike train the dataset's values *are* the times, so the field is the
input itself. A FIELD carries no numbers, so it cannot convert: the times dataset's
``value_unit`` must already be the clock's unit.

**The offset** (:func:`write_offset`): where one clock sits on another -- a segment within
its session, a recording within an experiment. A ``TRANSLATION`` when the two clocks share
a unit and a one-axis ``AFFINE`` when they do not, because a TRANSLATION states no factor
and the graph refuses a number-free edge between a millisecond axis and a second one.

Numbers on an edge are float64 in the *output* clock's unit; quantities on the wire and in
columns stay kanne's canonical integers (picoseconds, nanohertz). float64 seconds are exact
to the picosecond for about two and a half hours and good to ~15 ps over a day. The
reciprocal ``rate -> period -> rate`` round-trips exactly through nanohertz up to roughly
100 kHz and drifts in the last digit near 1 MHz; ask for the edge's ``affine`` when that matters.
"""

import datetime

from kanne_server import scalars as kanne_scalars

from core import enums, models
from core.creation import CreationContext
from core.logic import coords as coords_logic
from core.logic import graph as graph_logic

#: kanne's canonical integers: a Duration is picoseconds, a Frequency is nanohertz.
_PICOSECONDS_PER_SECOND = 1e12
_NANOHERTZ_PER_HERTZ = 1e9

#: The name of a clock's one axis.
CLOCK_AXIS = "t"


def seconds_in(unit: str, seconds: float) -> float:
    """``seconds`` expressed in ``unit``."""
    registry = kanne_scalars.get_registry()
    return float(registry.Quantity(seconds, "second").to(kanne_scalars.normalize_compact_units(unit)).magnitude)


def seconds_from(unit: str, value: float) -> float:
    """``value`` of ``unit``, in seconds."""
    registry = kanne_scalars.get_registry()
    return float(registry.Quantity(value, kanne_scalars.normalize_compact_units(unit)).to("second").magnitude)


def create_clock(*, name: str, unit: str = "second", epoch: datetime.datetime | None = None, ctx: CreationContext) -> "models.CoordinateSystem":
    """Mint a clock: a space with one TIME axis in ``unit``, optionally anchored to a wall-clock instant.

    ``epoch`` is where ``Block.recording_time`` went: ``wall_clock = epoch + t * unit`` is a
    property of the *space*, so two things laid out on one clock cannot disagree about when it
    started.
    """
    from core.inputs.coords import PhysicalAxisInputModel

    clock = models.CoordinateSystem.objects.create(name=name, epoch=epoch, creator=ctx.user, organization=ctx.organization)
    graph_logic.create_physical_axes(clock, [PhysicalAxisInputModel(name=CLOCK_AXIS, type=enums.AxisType.TIME, unit=unit)])
    return clock


def time_axis(system: "models.CoordinateSystem") -> "models.Axis | None":
    """The system's TIME axis. There is at most one: the database enforces it."""
    return next((axis for axis in system.axes.all() if axis.type == enums.AxisTypeChoices.TIME.value), None)


def clock_unit(clock: "models.CoordinateSystem") -> str:
    """The unit a clock counts in."""
    axis = time_axis(clock)
    if axis is None or not axis.unit:
        raise ValueError(f"'{clock.name}' is not a clock: a clock has a TIME axis carrying a time unit, which is what a sampling law is written in.")
    return axis.unit


def write_sampling_law(
    *,
    grid: "models.CoordinateSystem",
    clock: "models.CoordinateSystem",
    sampling_rate: int,
    t_start: int,
    ctx: CreationContext,
    name: str | None = None,
    validity: "enums.PlacementValidity | str | None" = None,
) -> "models.Transformation":
    """State ``t = sample * period + t_start`` as one edge, sample grid -> clock.

    ``sampling_rate`` and ``t_start`` are kanne's canonical integers (nanohertz, picoseconds).
    INFERRED by default: the numbers were read from acquisition metadata, and are as right as
    that metadata is.
    """
    sample_axis = time_axis(grid)
    if sample_axis is None:
        raise ValueError(
            f"'{grid.name}' has no TIME axis, so there is nothing for a sampling law to act on. The sample axis of a regularly sampled dataset is typed TIME; "
            "an INDEX axis has no metric, which is why a spike train reaches time through a lookup instead."
        )
    if sampling_rate <= 0:
        raise ValueError("A sampling rate is positive: a zero or negative rate maps every sample onto one instant, or runs time backwards.")

    unit = clock_unit(clock)
    period = seconds_in(unit, _NANOHERTZ_PER_HERTZ / sampling_rate)
    start = seconds_in(unit, t_start / _PICOSECONDS_PER_SECOND)

    return graph_logic.build_registration_edge(
        input_system=grid,
        output_system=clock,
        kind=enums.TransformKind.BY_DIMENSION,
        name=name,
        affine=[[period, start]],
        input_axes=[sample_axis.name],
        output_axes=[time_axis(clock).name],
        validity=validity or enums.PlacementValidity.INFERRED,
        ctx=ctx,
    )


def assert_is_times_dataset(times: "models.ArrayDataset", clock: "models.CoordinateSystem") -> None:
    """Refuse a times dataset whose values are not instants on this clock.

    A FIELD states no numbers, so unlike a sampling law it has nothing to convert with:
    values in milliseconds read against a clock in seconds would put every sample a
    thousandfold early, and nothing downstream could tell.
    """
    unit = clock_unit(clock)
    if not times.value_unit:
        raise ValueError(f"A dataset used as sample times must say what its values measure: give '{times.name}' a dataset-wide `valueUnit` anchor ('{unit}' for this clock) when it is created. Without it a time lookup would be a list of bare numbers.")
    coords_logic.assert_unit_matches_type(times.name, enums.AxisTypeChoices.TIME.value, times.value_unit)
    if not coords_logic.units_are_interchangeable(times.value_unit, unit):
        raise ValueError(
            f"The values of '{times.name}' are in '{times.value_unit}' but the clock '{clock.name}' counts in '{unit}'. A time lookup (a FIELD edge) states no numbers, "
            f"so it cannot convert between them: store the times in '{unit}', or give the block a `timeUnit` of '{times.value_unit}'."
        )


def write_time_lookup(
    *,
    grid: "models.CoordinateSystem",
    clock: "models.CoordinateSystem",
    times: "models.ArrayDataset",
    input_axis: str,
    ctx: CreationContext,
    name: str | None = None,
    validity: "enums.PlacementValidity | str | None" = None,
) -> "models.Transformation":
    """State "sample ``i`` was taken at ``times[i]``" as one FIELD edge, ``grid`` -> ``clock``.

    ``times`` must live alone in its system (rule R3, enforced by the graph where the field is
    named). When ``times`` lives in ``grid`` itself -- a spike train, whose values are its
    times -- the field is the input, and is stored as null so the dataset stays deletable under
    the field's PROTECT.
    """
    assert_is_times_dataset(times, clock)
    field = times.coordinate_system
    if field is None:
        raise ValueError(f"'{times.name}' has no coordinate system, so it cannot be the field of a time lookup.")

    return graph_logic.build_registration_edge(
        input_system=grid,
        output_system=clock,
        kind=enums.TransformKind.FIELD,
        name=name,
        input_axes=[input_axis],
        output_axes=[time_axis(clock).name],
        field=field,
        validity=validity or enums.PlacementValidity.INFERRED,
        ctx=ctx,
    )


def write_offset(
    *,
    source: "models.CoordinateSystem",
    target: "models.CoordinateSystem",
    offset: int,
    ctx: CreationContext,
    name: str | None = None,
    validity: "enums.PlacementValidity | str | None" = None,
) -> "models.Transformation":
    """State "``source``'s zero is ``offset`` into ``target``" as one edge between two clocks.

    ``offset`` is kanne's canonical picoseconds. MANUAL by default: someone decided where this
    recording sits, which is a different claim from one read off metadata.
    """
    source_unit, target_unit = clock_unit(source), clock_unit(target)
    start = seconds_in(target_unit, offset / _PICOSECONDS_PER_SECOND)
    axes = {"input_axes": [time_axis(source).name], "output_axes": [time_axis(target).name]}

    if coords_logic.units_are_interchangeable(source_unit, target_unit):
        # One unit on both sides: a bare offset. BY_DIMENSION so the two axes need not share a name.
        return graph_logic.build_registration_edge(
            input_system=source, output_system=target, kind=enums.TransformKind.BY_DIMENSION, name=name, translation=[start], validity=validity, ctx=ctx, **axes
        )

    # Two units: the edge has to state the factor, which a TRANSLATION cannot.
    factor = seconds_in(target_unit, seconds_from(source_unit, 1.0))
    return graph_logic.build_registration_edge(
        input_system=source, output_system=target, kind=enums.TransformKind.BY_DIMENSION, name=name, affine=[[factor, start]], validity=validity, ctx=ctx, **axes
    )


# --- what an interpretation checks before it times a dataset ---------------------------------------


def grid_of(dataset: "models.ArrayDataset") -> "models.CoordinateSystem":
    """The sample grid an interpretation times, or a refusal that says why there is none."""
    grid = dataset.coordinate_system
    if grid is None:
        raise ValueError(f"Dataset '{dataset.name}' has no coordinate system, so it is not in the graph and nothing can be timed against it.")
    return grid


class TimedOnce:
    """Refuses a second timing edge between one sample grid and one clock.

    Two edges between the same two spaces are *rivals* the path search chooses between, not
    a composition -- so a dataset named by two signals of one segment (or of two segments
    sharing the session clock) would have two answers to "when was sample 0", and the search
    would pick one. Checked against the database as well as this request, because the
    dataset may already be timed against a clock some other interpretation made.
    """

    def __init__(self) -> None:
        self._seen: set[tuple[int, int]] = set()

    def claim(self, dataset: "models.ArrayDataset", clock: "models.CoordinateSystem", label: str) -> None:
        key = (grid_of(dataset).pk, clock.pk)
        if key in self._seen or models.Transformation.objects.filter(input_id=key[0], output_id=key[1], parent__isnull=True).exists():
            raise ValueError(
                f"'{label}' names dataset '{dataset.name}', which is already timed against the clock '{clock.name}'. One dataset has one timing on one clock: "
                "a second edge between the same two spaces would be a rival answer, not a second signal. Give the segment its own clock (`timebase: OWN`), or name a lens' dataset instead."
            )
        self._seen.add(key)


def sample_count(dataset: "models.ArrayDataset", axis_name: str) -> int:
    """How many samples ``dataset`` has along ``axis_name``."""
    return dataset.shape_list[dataset.axis_names.index(axis_name)]


def assert_times_match(label: str, dataset: "models.ArrayDataset", sample_axis: str, times: "models.ArrayDataset") -> None:
    """A time lookup needs exactly one instant per sample: a one-dimensional dataset of the right length."""
    expected = [sample_count(dataset, sample_axis)]
    if times.shape_list != expected:
        raise ValueError(f"'{label}' has {expected[0]} samples along '{sample_axis}' but its times dataset '{times.name}' has shape {times.shape_list}: a time lookup needs exactly one instant per sample.")


# --- reading the facts back -----------------------------------------------------------------------
#
# Derived, never stored: the edge is the fact, and these are readings of it. They answer
# None rather than raise when the edge is not the shape they read -- a lookup has no rate.


def _law_between(source: "models.CoordinateSystem | None", target: "models.CoordinateSystem | None") -> "tuple[float, float, str] | None":
    """``(factor, constant, target_unit)`` of the one-axis affine law from ``source`` to ``target``, if that is what relates them."""
    if source is None or target is None:
        return None
    edge = models.Transformation.objects.filter(input=source, output=target, parent__isnull=True, selector__isnull=True).order_by("pk").first()
    if edge is None or edge.kind != enums.TransformKindChoices.BY_DIMENSION.value:
        return None
    params = edge.params or {}
    if params.get("affine"):
        factor, constant = params["affine"][0][0], params["affine"][0][-1]
    elif params.get("translation") is not None:
        factor, constant = 1.0, params["translation"][0]
    elif params.get("scale") is not None:
        factor, constant = params["scale"][0], 0.0
    else:
        return None
    return float(factor), float(constant), clock_unit(target)


def sampling_of(grid: "models.CoordinateSystem | None", clock: "models.CoordinateSystem | None") -> tuple[int | None, int | None]:
    """``(sampling_rate, t_start)`` as canonical integers (nanohertz, picoseconds), read off the sampling law.

    ``(None, None)`` when the dataset is timed by a lookup, or not timed at all.
    """
    law = _law_between(grid, clock)
    if law is None or law[0] <= 0:
        return None, None
    period, start, unit = law
    rate = _NANOHERTZ_PER_HERTZ / seconds_from(unit, period)
    return int(round(rate)), int(round(seconds_from(unit, start) * _PICOSECONDS_PER_SECOND))


def offset_of(source: "models.CoordinateSystem | None", target: "models.CoordinateSystem | None") -> int | None:
    """Where ``source``'s zero sits on ``target``, in canonical picoseconds. None when no offset edge relates them."""
    law = _law_between(source, target)
    if law is None:
        return None
    _, start, unit = law
    return int(round(seconds_from(unit, start) * _PICOSECONDS_PER_SECOND))


def times_dataset_of(grid: "models.CoordinateSystem | None", clock: "models.CoordinateSystem | None") -> "models.ArrayDataset | None":
    """The dataset whose values time ``grid``'s samples on ``clock``, read off the time lookup. None for a sampled dataset."""
    if grid is None or clock is None:
        return None
    edge = models.Transformation.objects.filter(input=grid, output=clock, parent__isnull=True, kind=enums.TransformKindChoices.FIELD.value).order_by("pk").first()
    if edge is None:
        return None
    return next(iter(edge.effective_field.datasets.all()[:1]), None)
