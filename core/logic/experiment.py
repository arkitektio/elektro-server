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

What each source becomes is decided from what it *is*, never from a guess about its shape:

* an **array dataset** with a TIME axis is a TRACE over its whole-dataset lens -- unless its
  values are some FIELD's map (a times dataset is a lookup, not a signal);
* a **sparse dataset** with a TIME axis is SPIKES;
* a **table dataset** with a TIME coordinate column is EVENTS;
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
    enums.ExperimentLayerKindChoices.TRACE.value: "lens",
    enums.ExperimentLayerKindChoices.SPIKES.value: "sparse_dataset",
    enums.ExperimentLayerKindChoices.EVENTS.value: "table_dataset",
    enums.ExperimentLayerKindChoices.ANNOTATION.value: "annotation_collection",
}

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
    expected = {
        enums.ExperimentLayerKindChoices.TRACE.value: models.Lens,
        enums.ExperimentLayerKindChoices.SPIKES.value: models.SparseDataset,
        enums.ExperimentLayerKindChoices.EVENTS.value: models.TableDataset,
        enums.ExperimentLayerKindChoices.ANNOTATION.value: models.AnnotationCollection,
    }[kind]
    if not isinstance(source, expected):
        raise ValueError(f"A {kind} layer draws a {expected.__name__}, but {source_label(source)} is a {type(source).__name__}.")
    if kind == enums.ExperimentLayerKindChoices.SPIKES.value and not has_time_axis(source.coordinate_system):
        raise ValueError(
            f"Sparse dataset {source_label(source)} has no TIME axis, so it is not a spike raster: there is no sample axis to draw a tick along. "
            "A raster is created with one INDEX axis (the units) and one TIME axis (the samples)."
        )
    if kind == enums.ExperimentLayerKindChoices.EVENTS.value and time_column(source) is None:
        raise ValueError(
            f"Table {source_label(source)} has no TIME coordinate column, so its rows have no instant to be drawn at. Declare the column holding each event's time with `axisType: TIME`."
        )


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
    if not world.axes.filter(type=enums.AxisTypeChoices.TIME.value).exists():
        raise ValueError(f"'{world.name}' has no TIME axis, so it is not something data can be laid out along in time.")
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
    include_spikes: bool = True
    include_events: bool = True
    include_annotations: bool = True
    skip_unplaceable: bool = False


def _times_systems() -> "set[int]":
    """The spaces whose data is some FIELD's map: a times dataset is a lookup, not a signal."""
    return set(models.Transformation.objects.filter(field__isnull=False).values_list("field_id", flat=True))


def candidates(system: "models.CoordinateSystem", organization, policy: Policy) -> list:  # noqa: ANN001 - an Organization
    """What a bootstrap over ``system`` would draw, in layer order: traces, spikes, events, annotations.

    The loose reachable set -- the same one ``inView`` reads, FIELD routes included, clock chains
    included (divergence 1) -- then one query per container kind, organization-scoped: a shared
    clock can have co-tenants whose data this request may not see.
    """
    reachable = graph_logic.placeable_system_ids_in(system, require_affine=False)
    if not reachable:
        return []
    time = enums.AxisTypeChoices.TIME.value
    timed_systems = models.Axis.objects.filter(type=time).values("coordinate_system_id")
    found: list = []
    if policy.include_traces:
        fields = _times_systems()
        datasets = (
            models.ArrayDataset.objects.filter(coordinate_system_id__in=reachable, organization=organization)
            .filter(coordinate_system_id__in=timed_systems)
            .exclude(coordinate_system_id__in=fields)
            .order_by("pk")
        )
        found.extend(datasets)
    if policy.include_spikes:
        found.extend(models.SparseDataset.objects.filter(coordinate_system_id__in=reachable, organization=organization).filter(coordinate_system_id__in=timed_systems).order_by("pk"))
    if policy.include_events:
        found.extend(models.TableDataset.objects.filter(coordinate_system_id__in=reachable, organization=organization).filter(coordinate_system_id__in=timed_systems).order_by("pk"))
    if policy.include_annotations:
        found.extend(models.AnnotationCollection.objects.filter(coordinate_system_id__in=reachable, organization=organization).order_by("pk"))
    return found


_KIND_OF: dict[type, str] = {
    models.ArrayDataset: enums.ExperimentLayerKindChoices.TRACE.value,
    models.SparseDataset: enums.ExperimentLayerKindChoices.SPIKES.value,
    models.TableDataset: enums.ExperimentLayerKindChoices.EVENTS.value,
    models.AnnotationCollection: enums.ExperimentLayerKindChoices.ANNOTATION.value,
}


def _defaults_for(kind: str, source) -> dict:  # noqa: ANN001
    """The render settings a bootstrapped layer starts with -- read off recorded facts, or defaulted."""
    if kind == enums.ExperimentLayerKindChoices.SPIKES.value:
        return {"tick_height": 0.8, "value_mode": enums.SpikeValueModeChoices.PRESENCE.value}
    if kind == enums.ExperimentLayerKindChoices.EVENTS.value:
        label = source.columns.filter(role=enums.ColumnRoleChoices.LABEL.value).order_by("order").first()
        return {"label_column": label.name if label is not None else None, "stop_column": _stop_column(source)}
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
        for source in candidates(system, ctx.organization, policy)[: policy.nchildren]:
            kind = _KIND_OF[type(source)]
            target = whole_lens(source, ctx) if isinstance(source, models.ArrayDataset) else source
            if policy.skip_unplaceable:
                system_ = source_system_of(target)
                if system_ is None or not graph_logic.is_placeable_in(system, system_, require_affine=False):
                    continue
            create_layer(experiment, kind=kind, source=target, order=order, **_defaults_for(kind, source))
            order += 1
    return experiment
