"""Creating experiments and their layers over spaces that already exist.

The counterpart of mikro's ``core/logic/scene.py``. :func:`bootstrap_experiment_from_system`
is the CS-first way data gets staged: point it at a clock -- a session's, a run's, a world --
and it materializes a layer for everything laid out on it. It composes only facts that already
exist (the space, the edges onto it, the axis types, a table's declared columns) into ordinary
rows -- an ordinary experiment, ordinary lenses, ordinary layers -- and **authors no edges**.
Nothing here fabricates a placement: data with no route to the world is refused (or, under
``skip_unplaceable``, left out), with the way to give it one.

**The gate is reachability, not affinity** (``core/DESIGN.md``, divergence 2). mikro's rfc10
refuses a layer whose route does not condense into one affine map; a timeline draws samples at
looked-up instants without a matrix, so a FIELD route is admitted here and ``asAffine`` on such
a layer says why it has none.

What each source becomes is decided from what it *is*, never from a guess about its shape
(:func:`kind_for`):

* an **array dataset** with a TIME axis is a TRACE over its whole-dataset lens -- a HEATMAP when
  it also has a FREQUENCY axis (a spectrogram), a WAVEFORM when it has an INDEX axis and was
  derived from a spike raster (per-unit templates) -- and nothing when its values are some FIELD's
  map (a times dataset is a lookup, not a signal);
* a **sparse dataset** with a TIME axis is SPIKES;
* a **table dataset** with a TIME coordinate column is EVENTS -- or SERIES when its one numeric,
  non-time attribute is the point of it (running speed); with SPACE coordinate columns and no
  TIME column it is POINT (a channel map);
* an **annotation collection** is ANNOTATION.
"""

import dataclasses

from django.db import transaction

from core import enums, models
from core.creation import CreationContext
from core.logic import coordinate_system as coordinate_system_logic
from core.logic import graph as graph_logic

#: Which source FK each kind carries. The model's CheckConstraint states the same, and the
#: builder checks it first so a caller hears a sentence rather than an IntegrityError.
SOURCE_FIELD: dict[str, str] = {
    **{kind: "lens" for kind in enums.LENS_BACKED_KINDS},
    enums.ExperimentLayerKindChoices.SPIKES.value: "sparse_dataset",
    **{kind: "table_dataset" for kind in enums.TABLE_BACKED_KINDS},
    enums.ExperimentLayerKindChoices.ANNOTATION.value: "annotation_collection",
}

_KIND = enums.ExperimentLayerKindChoices
_AXIS = enums.AxisTypeChoices

#: How a layer composites by default, per kind. Every one draws *over* what is beneath it --
#: summing two voltages' pixels (mikro's ADDITIVE, right for fluorescence) means nothing here.
_DEFAULT_BLENDING = enums.BlendingChoices.NORMAL.value


def source_label(source) -> str:  # noqa: ANN001 - a lens, sparse dataset, table dataset or collection
    """What to call a layer's source in a refusal."""
    if isinstance(source, models.Lens):
        return f"lens {source.pk} over '{source.dataset.name}'"
    return f"'{getattr(source, 'name', source.pk)}'"


def source_system_of(source) -> "models.CoordinateSystem | None":  # noqa: ANN001
    """The space a layer over ``source`` would draw in: :func:`graph_logic.layer_source_system`'s answer, before the layer exists."""
    if isinstance(source, models.Lens):
        return graph_logic.lens_source_system(source)
    return getattr(source, "coordinate_system", None)


def assert_reaches(world: "models.CoordinateSystem", source) -> None:  # noqa: ANN001
    """Refuse a layer whose data has no route into the world. Deliberately looser than mikro's gate: a FIELD route counts."""
    system = source_system_of(source)
    if system is None:
        raise ValueError(f"{source_label(source)} has no coordinate system, so it is not in the graph and cannot be laid out on a timeline.")
    if graph_logic.is_placeable_in(world, system, require_affine=False):
        return
    raise ValueError(
        f"Nothing relates {source_label(source)} to '{world.name}', so there is nowhere on this timeline to draw it. Time its samples on a clock "
        "(`createSamplingLaw`, or a FIELD `createTransformation` for a lookup) and relate that clock to the world (`createClockOffset`), or build the "
        "experiment over the clock it is already timed on (`createExperimentFromCoordinateSystem`). Nothing is placed by default: an assumed offset of zero "
        "cannot be told from a measured one."
    )


def assert_kind(kind: str, source) -> None:  # noqa: ANN001
    """Refuse a source a kind cannot draw, naming what it can."""
    if kind in enums.LENS_BACKED_KINDS:
        expected = models.Lens
    elif kind in enums.TABLE_BACKED_KINDS:
        expected = models.TableDataset
    else:
        expected = {_KIND.SPIKES.value: models.SparseDataset, _KIND.ANNOTATION.value: models.AnnotationCollection}[kind]
    if not isinstance(source, expected):
        raise ValueError(f"A {kind} layer draws a {expected.__name__}, but {source_label(source)} is a {type(source).__name__}.")

    if kind == _KIND.SPIKES.value and not has_time_axis(source.coordinate_system):
        raise ValueError(
            f"Sparse dataset {source_label(source)} has no TIME axis, so it is not a spike raster: there is no sample axis to draw a tick along. "
            "A raster is created with one INDEX axis (the units) and one TIME axis (the samples)."
        )
    if kind in (_KIND.EVENTS.value, _KIND.SERIES.value) and time_column(source) is None:
        raise ValueError(
            f"Table {source_label(source)} has no TIME coordinate column, so its rows have no instant to be drawn at. Declare the column holding each row's time with `axisType: TIME`."
        )
    if kind == _KIND.POINT.value:
        if time_column(source) is not None:
            raise ValueError(
                f"Table {source_label(source)} has a TIME coordinate column: its rows are events, not places. A point layer draws a table placed in space -- a channel map, "
                "units at their positions -- whose coordinate columns are SPACE only."
            )
        if len(space_columns(source)) < 2:
            raise ValueError(f"Table {source_label(source)} has fewer than two SPACE coordinate columns, so a row is not a point in a plane. Declare its x and y columns with `axisType: SPACE`.")
    if kind in (_KIND.TRACE.value, _KIND.HEATMAP.value, _KIND.WAVEFORM.value) and not lens_axes(source, _AXIS.TIME.value):
        raise ValueError(f"The dataset under {source_label(source)} has no TIME axis, so there is nothing to draw it along. A {kind} layer draws samples over time.")
    if kind == _KIND.WAVEFORM.value and len(lens_axes(source, _AXIS.INDEX.value)) != 1:
        raise ValueError(
            f"The dataset under {source_label(source)} has {len(lens_axes(source, _AXIS.INDEX.value))} INDEX axes, but waveform templates have exactly one: the units, "
            "one template each, shaped (unit, [c,] w)."
        )


def lens_axes(lens: "models.Lens", axis_type: str) -> list[str]:
    """The names of the lens' dataset axes of one type, in the dataset's order."""
    system = lens.dataset.coordinate_system
    if system is None:
        return []
    return [axis.name for axis in system.axes.all().order_by("order") if axis.type == axis_type]


def resolve_row_axis(lens: "models.Lens", requested: str | None) -> str:
    """The axis a heatmap draws down the image: the one named, or FREQUENCY, else CHANNEL, else INDEX.

    Every *other* axis of the lens but TIME must have extent one: a heatmap is an image, and a
    third axis with more than one position would be a stack of them with nothing to say which.
    """
    system = lens.dataset.coordinate_system
    types = {axis.name: axis.type for axis in system.axes.all()} if system is not None else {}
    if requested is not None:
        if requested not in types:
            raise ValueError(f"`rowAxis` is '{requested}', but the dataset under {source_label(lens)} has axes {sorted(types)}.")
        if types[requested] in (_AXIS.TIME.value, _AXIS.SPACE.value):
            raise ValueError(f"`rowAxis` '{requested}' is a {types[requested]} axis. A heatmap draws time across and one enumerated or spectral axis down: FREQUENCY, CHANNEL or INDEX.")
        row = requested
    else:
        row = next((name for kind in (_AXIS.FREQUENCY.value, _AXIS.CHANNEL.value, _AXIS.INDEX.value) for name in lens_axes(lens, kind)), None)
        if row is None:
            raise ValueError(f"The dataset under {source_label(lens)} has no FREQUENCY, CHANNEL or INDEX axis, so there is nothing to draw down a heatmap. Draw it as a trace.")
    stacked = [name for name, axis_type in types.items() if name != row and axis_type != _AXIS.TIME.value and lens.get_size_of_axis(name) > 1]
    if stacked:
        raise ValueError(
            f"A heatmap is one image, time across and '{row}' down, but {source_label(lens)} also spans {stacked} with more than one position. Cut a lens that fixes "
            f"{'it' if len(stacked) == 1 else 'them'} to one position (`createLens` with a slice of one) and draw that."
        )
    return row


def resolve_unit_axis(lens: "models.Lens", requested: str | None) -> str:
    """The axis a waveform layer enumerates units along: the one named, or the lens' one INDEX axis."""
    index = lens_axes(lens, _AXIS.INDEX.value)
    if requested is None:
        return index[0]
    if requested not in index:
        raise ValueError(f"`unitAxis` is '{requested}', but the INDEX axes of the dataset under {source_label(lens)} are {index}.")
    return requested


def space_columns(table: "models.TableDataset") -> "list[models.Column]":
    """A table's SPACE coordinate columns, in declared order."""
    return list(table.columns.filter(role=enums.ColumnRoleChoices.COORDINATE.value, axis_type=_AXIS.SPACE.value).order_by("order"))


def assert_numeric_column(table: "models.TableDataset", name: str | None, what: str) -> None:
    """Refuse a column a layer reads as a number when the table does not declare it numeric."""
    from core.logic import tables as tables_logic

    if name is None:
        return
    assert_column(table, name, what)
    column = table.columns.get(name=name)
    if not tables_logic.is_numeric(column.dtype):
        raise ValueError(f"`{what}` names column '{name}' of {source_label(table)}, whose type is {column.dtype}: it is drawn as a number, so it has to hold one.")


def has_time_axis(system: "models.CoordinateSystem | None") -> bool:
    return system is not None and system.axes.filter(type=enums.AxisTypeChoices.TIME.value).exists()


def time_column(table: "models.TableDataset") -> "models.Column | None":
    """A table's TIME coordinate column -- where each row sits in its own space -- or None."""
    return table.columns.filter(role=enums.ColumnRoleChoices.COORDINATE.value, axis_type=enums.AxisTypeChoices.TIME.value).order_by("order").first()


def assert_column(table: "models.TableDataset | None", name: str | None, what: str) -> None:
    """Refuse a render column the table does not declare."""
    if name is None:
        return
    if table is None or not table.columns.filter(name=name).exists():
        raise ValueError(f"`{what}` names column '{name}', which {'no table' if table is None else f'table {source_label(table)}'} declares.")


def whole_lens(dataset: "models.ArrayDataset", ctx: CreationContext) -> "models.Lens":
    """A dataset's unsliced lens, reused when there is one: an unsliced lens owns no space, so a second would say nothing the first did not."""
    return models.Lens.objects.filter(dataset=dataset, slices=[]).order_by("pk").first() or coordinate_system_logic.create_lens(dataset, [], ctx)


def create_layer(experiment: "models.Experiment", *, kind: str, source, order: int | None = None, name: str | None = None, **settings) -> "models.ExperimentLayer":  # noqa: ANN001, ANN003
    """Write one layer: check the kind can draw the source and that it reaches the world, then append it."""
    assert_kind(kind, source)
    assert_reaches(experiment.world, source)
    if kind == enums.ExperimentLayerKindChoices.ANNOTATION.value and experiment.layers.filter(annotation_collection=source).exists():
        raise ValueError(f"{source_label(source)} is already drawn in experiment '{experiment.name}'. One layer per collection: style its annotations instead.")
    # The one setting each of these kinds cannot draw without, resolved (and checked) here so the
    # generic `createLayer` gets the same answer as the per-kind mutation.
    if kind == _KIND.HEATMAP.value:
        settings["row_axis"] = resolve_row_axis(source, settings.get("row_axis"))
    elif kind == _KIND.WAVEFORM.value:
        settings["unit_axis"] = resolve_unit_axis(source, settings.get("unit_axis"))
    elif kind == _KIND.SERIES.value:
        value = settings.get("value_column") or _series_value_column(source)
        if value is None:
            raise ValueError(f"A series layer draws one numeric column of {source_label(source)} over time, and the table has no single such column to default to: name the `valueColumn`.")
        assert_numeric_column(source, value, "valueColumn")
        start = time_column(source)
        if start is not None and value == start.name:
            raise ValueError(f"`valueColumn` is '{value}', the table's TIME column: a series draws a value *against* time, not time against itself.")
        settings["value_column"] = value
    if order is None:
        order = experiment.layers.count()
    settings.setdefault("blending", _DEFAULT_BLENDING)
    return models.ExperimentLayer.objects.create(
        experiment=experiment,
        kind=kind,
        name=name if name is not None else _default_name(source),
        order=order,
        **{SOURCE_FIELD[kind]: source},
        **settings,
    )


def _default_name(source) -> str | None:  # noqa: ANN001
    if isinstance(source, models.Lens):
        return source.dataset.name
    return getattr(source, "name", None)


def create_experiment(
    *,
    name: str,
    ctx: CreationContext,
    description: str | None = None,
    world: "models.CoordinateSystem | None" = None,
    axes: list | None = None,
    epoch=None,  # noqa: ANN001 - a datetime
) -> "models.Experiment":
    """Create an experiment over a world: an adopted existing system, or one minted for convenience.

    mikro's ``create_scene``. Adopting composes over the space as it is -- many experiments can
    share it, and its axes and epoch are already its own. Without ``world`` an ordinary
    ownerless space is minted first (by default a clock in seconds with no epoch) and adopted.
    """
    if world is not None:
        if axes is not None or epoch is not None:
            raise ValueError("An experiment adopting an existing coordinate system takes its axes and epoch from it; do not pass `axes` or `epoch` alongside `coordinateSystem`.")
    else:
        world = coordinate_system_logic.create_world_space(name=f"{name}/world", axes=axes, epoch=epoch, ctx=ctx)
    if not world.axes.filter(type__in=[_AXIS.TIME.value, _AXIS.SPACE.value]).exists():
        raise ValueError(
            f"'{world.name}' has no TIME or SPACE axis, so there is nowhere to lay data out along: an experiment composes over a timeline (a clock) or a place (a probe's space)."
        )
    return models.Experiment.objects.create(
        name=name,
        description=description,
        creator=ctx.user,
        organization=ctx.organization,
        world=world,
    )


@dataclasses.dataclass
class Policy:
    """What :func:`bootstrap_experiment_from_system` stages. Mirrors mikro's ``ScenePolicyInputModel``."""

    nchildren: int = 32
    include_traces: bool = True
    include_heatmaps: bool = True
    include_waveforms: bool = True
    include_spikes: bool = True
    include_events: bool = True
    include_series: bool = True
    include_points: bool = True
    include_annotations: bool = True
    skip_unplaceable: bool = False

    def admits(self, kind: str) -> bool:
        return {
            _KIND.TRACE.value: self.include_traces,
            _KIND.HEATMAP.value: self.include_heatmaps,
            _KIND.WAVEFORM.value: self.include_waveforms,
            _KIND.SPIKES.value: self.include_spikes,
            _KIND.EVENTS.value: self.include_events,
            _KIND.SERIES.value: self.include_series,
            _KIND.POINT.value: self.include_points,
            _KIND.ANNOTATION.value: self.include_annotations,
        }[kind]


def _times_systems() -> "set[int]":
    """The spaces whose data is some FIELD's map: a times dataset is a lookup, not a signal."""
    return set(models.Transformation.objects.filter(field__isnull=False).values_list("field_id", flat=True))


def candidates(system: "models.CoordinateSystem", organization, policy: Policy) -> "list[tuple[str, object]]":  # noqa: ANN001 - an Organization
    """What a bootstrap over ``system`` would draw, as ``(kind, source)`` in layer order: arrays, rasters, tables, annotations.

    The loose reachable set -- the same one ``inView`` reads, FIELD routes included, clock chains
    included (divergence 1) -- then one query per container kind, organization-scoped: a shared
    clock can have co-tenants whose data this request may not see. What each source becomes is
    :func:`kind_for`'s; the policy then admits or drops that kind.
    """
    reachable = graph_logic.placeable_system_ids_in(system, require_affine=False)
    if not reachable:
        return []
    fields = _times_systems()
    sources: list = [
        *models.ArrayDataset.objects.filter(coordinate_system_id__in=reachable, organization=organization).exclude(coordinate_system_id__in=fields).order_by("pk"),
        *models.SparseDataset.objects.filter(coordinate_system_id__in=reachable, organization=organization).order_by("pk"),
        *models.TableDataset.objects.filter(coordinate_system_id__in=reachable, organization=organization).order_by("pk"),
        *models.AnnotationCollection.objects.filter(coordinate_system_id__in=reachable, organization=organization).order_by("pk"),
    ]
    # One query for every array's "was I derived from a raster?", rather than two per array.
    raster_derived = _raster_derived_systems([source.coordinate_system_id for source in sources if isinstance(source, models.ArrayDataset)])
    found = []
    for source in sources:
        kind = kind_for(source, raster_derived=raster_derived)
        if kind is not None and policy.admits(kind):
            found.append((kind, source))
    return found


def kind_for(source, *, raster_derived: "set[int] | None" = None) -> str | None:  # noqa: ANN001
    """How a bootstrap draws a source, or None when it is nothing a timeline or a place draws.

    ``raster_derived`` is the batched answer to "which array grids have a derivation edge into a
    raster's space" (:func:`_raster_derived_systems`); without it, the question is asked per source.
    """
    if isinstance(source, models.AnnotationCollection):
        return _KIND.ANNOTATION.value
    system = source.coordinate_system
    types = [axis.type for axis in system.axes.all()] if system is not None else []
    if isinstance(source, models.SparseDataset):
        return _KIND.SPIKES.value if _AXIS.TIME.value in types else None
    if isinstance(source, models.TableDataset):
        if time_column(source) is None:
            return _KIND.POINT.value if len(space_columns(source)) >= 2 else None
        return _KIND.SERIES.value if _series_value_column(source) is not None else _KIND.EVENTS.value
    if _AXIS.TIME.value not in types:
        return None
    if _AXIS.FREQUENCY.value in types:
        return _KIND.HEATMAP.value
    derived = (source.coordinate_system_id in raster_derived) if raster_derived is not None else _derived_from_a_raster(source)
    if types.count(_AXIS.INDEX.value) == 1 and derived:
        return _KIND.WAVEFORM.value
    return _KIND.TRACE.value


def _raster_derived_systems(system_ids: "list[int]") -> "set[int]":
    """Among these array grids, the ones with a top-level edge into a space a sparse dataset lives in -- a derivation from a raster."""
    ids = [pk for pk in system_ids if pk is not None]
    if not ids:
        return set()
    return set(
        models.Transformation.objects.filter(input_id__in=ids, parent__isnull=True, output__sparse_datasets__isnull=False).values_list("input_id", flat=True)
    )


def _derived_from_a_raster(dataset: "models.ArrayDataset") -> bool:
    """Whether a dataset's primary parent is a sparse dataset -- what makes (unit, c, w) templates rather than any array."""
    from core.logic import ephys_pickers

    return ephys_pickers.raster_parent(dataset) is not None


def _series_value_column(table: "models.TableDataset") -> str | None:
    """The one numeric attribute a table with a TIME column is *about*, if it is a series rather than a list of events.

    A series is a quantity sampled in rows: one numeric ATTRIBUTE that is not itself a time (a
    stop column is an interval's end, which makes the rows events), and no LABEL column (a named
    row is an event). Inferred only when unambiguous.
    """
    from core.logic import coords as coords_logic
    from core.logic import tables as tables_logic

    start = time_column(table)
    columns = list(table.columns.all())
    if any(column.role == enums.ColumnRoleChoices.LABEL.value for column in columns):
        return None
    numeric = [
        column.name
        for column in columns
        if column.role == enums.ColumnRoleChoices.ATTRIBUTE.value
        and tables_logic.is_numeric(column.dtype)
        and not (column.unit and start is not None and start.unit and coords_logic.units_are_interchangeable(column.unit, start.unit))
    ]
    return numeric[0] if len(numeric) == 1 else None


def value_window(dataset: "models.ArrayDataset") -> tuple[float | None, float | None]:
    """The display range a dataset's dataset-wide ValueHistogram recorded: p1/p99, else min/max. mikro's ``_value_windows``, for the whole dataset."""
    histogram = models.ValueHistogram.objects.filter(anchor__dataset=dataset, anchor__coordinates={}).first()
    if histogram is None:
        return None, None
    low = histogram.p1 if histogram.p1 is not None else histogram.min
    high = histogram.p99 if histogram.p99 is not None else histogram.max
    return low, high


def _defaults_for(kind: str, source) -> dict:  # noqa: ANN001
    """The render settings a bootstrapped layer starts with -- read off recorded facts, or defaulted."""
    if kind == _KIND.SPIKES.value:
        return {"tick_height": 0.8, "value_mode": enums.SpikeValueModeChoices.PRESENCE.value}
    if kind == _KIND.EVENTS.value:
        label = source.columns.filter(role=enums.ColumnRoleChoices.LABEL.value).order_by("order").first()
        return {"label_column": label.name if label is not None else None, "stop_column": _stop_column(source)}
    if kind == _KIND.SERIES.value:
        return {"value_column": _series_value_column(source)}
    if kind in (_KIND.TRACE.value, _KIND.HEATMAP.value):
        low, high = value_window(source)
        defaults = {"clim_min": low, "clim_max": high}
        if kind == _KIND.HEATMAP.value:
            defaults["colormap"] = enums.ColorMapChoices.VIRIDIS.value
        return defaults
    return {}


def _stop_column(table: "models.TableDataset") -> str | None:
    """The one ATTRIBUTE column whose unit is a time interchangeable with the TIME column's, if exactly one is.

    Inferred only when unambiguous: two candidates (a stop and a duration, say) is a choice for
    the caller, not something to guess.
    """
    from core.logic import coords as coords_logic

    start = time_column(table)
    if start is None or not start.unit:
        return None
    candidates_ = [
        column.name
        for column in table.columns.filter(role=enums.ColumnRoleChoices.ATTRIBUTE.value, unit__isnull=False).order_by("order")
        if coords_logic.units_are_interchangeable(column.unit, start.unit)
    ]
    return candidates_[0] if len(candidates_) == 1 else None


def bootstrap_experiment_from_system(
    system: "models.CoordinateSystem",
    *,
    name: str | None,
    policy: Policy,
    ctx: CreationContext,
) -> "models.Experiment":
    """An experiment over ``system``, with a layer for everything laid out on it. CS-first.

    One transaction: a source refused by the gate (with ``skip_unplaceable`` off) takes the whole
    experiment with it rather than leaving half a staging behind.
    """
    with transaction.atomic():
        experiment = create_experiment(name=name or system.name, world=system, ctx=ctx)
        order = 0
        for kind, source in candidates(system, ctx.organization, policy)[: policy.nchildren]:
            target = whole_lens(source, ctx) if isinstance(source, models.ArrayDataset) else source
            if policy.skip_unplaceable:
                system_ = source_system_of(target)
                if system_ is None or not graph_logic.is_placeable_in(system, system_, require_affine=False):
                    continue
            settings = _defaults_for(kind, source)
            if kind == _KIND.HEATMAP.value:
                settings["row_axis"] = resolve_row_axis(target, None)
            if kind == _KIND.WAVEFORM.value:
                settings["unit_axis"] = resolve_unit_axis(target, None)
            create_layer(experiment, kind=kind, source=target, order=order, **settings)
            order += 1
    return experiment
