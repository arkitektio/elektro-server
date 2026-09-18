"""Shared builders for the coordinate-graph tests.

Ported from mikro's ``tests/seed.py``, which the vendored tests import by name. A world
stands where mikro seeds a scene.

Every helper creates rows in the organization and user of the supplied context (the
identity the static "test" token resolves to, see conftest.py). They are the ORM mirror
of the mutations, so a test about the graph does not have to go through GraphQL -- or
through an object store -- to get a well-formed dataset: a level carries its ``shape``
itself, which is all the graph ever reads of it, so no store is needed at all.
"""

import uuid

from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import enums
from core.creation import CreationContext
from core.inputs.coords import (
    AffineTransformInputModel,
    AxisInputModel,
    PhysicalAxisInputModel,
    RegistrationPathInputModel,
    ScaleTransformInputModel,
    TranslationTransformInputModel,
)
from core.logic import coordinate_system as coordinate_system_logic
from core.logic import graph as graph_logic
from core.logic import coords as coords_logic
from core.models import ArrayDataset, CoordinateAnchor, CoordinateSystem, DataArray, File, Folder, Lens, ValueUnit
from datalayer.models import SparseStore, sparse_layout_path


def axis(name: str, type_: enums.AxisType) -> AxisInputModel:
    """One structural axis of a test dataset's sample grid."""
    return AxisInputModel(name=name, type=type_)


def physical_axis(name: str, type_: enums.AxisType, unit: str) -> PhysicalAxisInputModel:
    """One axis of a unit-carrying space: a clock, a world."""
    return PhysicalAxisInputModel(name=name, type=type_, unit=unit)


#: A multichannel recording: samples over time, by channel. The shape Neo calls an AnalogSignal.
TC_AXES = [
    axis("t", enums.AxisType.TIME),
    axis("c", enums.AxisType.CHANNEL),
]

#: A single-channel recording.
T_AXES = [
    axis("t", enums.AxisType.TIME),
]

#: A neuron model's config with one cell, ``soma``, of one section, ``0``: the model a site's
#: ``cell: "soma", location: "0"`` is part of. Only the ids a site is checked against.
SOMA_MODEL = {"cells": [{"id": "soma", "biophysics": {"compartments": []}, "topology": {"sections": [{"id": "0", "length": "20 um"}]}}]}

#: A spike train's times dataset: one value per spike, and a spike number has no metric.
SPIKE_AXES = [
    axis("spike", enums.AxisType.INDEX),
]

#: mikro's fixtures, kept under mikro's names for the vendored tests that are about the
#: graph rather than about what the axes mean. The arithmetic is generic over axis types.
SIMPLE_AXES = [
    axis("c", enums.AxisType.CHANNEL),
    axis("y", enums.AxisType.SPACE),
    axis("x", enums.AxisType.SPACE),
]
ZYX_AXES = [
    axis("z", enums.AxisType.SPACE),
    axis("y", enums.AxisType.SPACE),
    axis("x", enums.AxisType.SPACE),
]
YX_AXES = [
    axis("y", enums.AxisType.SPACE),
    axis("x", enums.AxisType.SPACE),
]

#: A clock: what an experiment's world is by default.
CLOCK_AXES = [
    physical_axis("t", enums.AxisType.TIME, "second"),
]

#: A spatial world, for the vendored tests that register (z, y, x) sources.
ZYX_WORLD_AXES = [
    physical_axis("z", enums.AxisType.SPACE, "micrometer"),
    physical_axis("y", enums.AxisType.SPACE, "micrometer"),
    physical_axis("x", enums.AxisType.SPACE, "micrometer"),
]


def _creation(ctx: HttpContext) -> CreationContext:
    return CreationContext(
        user=ctx.request.user,
        organization=ctx.request.organization,
        membership=ctx.request.membership,
        task=None,
    )


def _seed_array_dataset_sync(ctx: HttpContext, name: str, axes: list, shapes: list[list[int]], system: CoordinateSystem | None, value_unit: str | None, folder: Folder | None) -> ArrayDataset:
    """Build a dataset, its coordinate systems, and the edges placing each level in its sample grid.

    mikro's seeder, plus the two things this service's tests ask for: a supplied ``system``
    (several datasets may share one frame) and a dataset-wide ``value_unit`` anchor.
    """
    creation = _creation(ctx)
    axis_specs = [coords_logic.AxisSpec(name=a.name, type=a.type.value) for a in axes]

    # The space, then the data that lives in it.
    intrinsic = system
    if intrinsic is None:
        intrinsic = CoordinateSystem.objects.create(name=f"{name}/intrinsic", creator=creation.user, organization=creation.organization)
    dataset = ArrayDataset.objects.create(name=name, coordinate_system=intrinsic, folder=folder, creator=creation.user, organization=creation.organization)
    if system is None:
        graph_logic.create_pixel_axes(intrinsic, axes)

    for level, shape in enumerate(shapes):
        # Level 0 lives in the dataset's own grid: it IS that grid.
        array_system = intrinsic
        if level:
            array_system = CoordinateSystem.objects.create(name=f"{name}/{level}", creator=creation.user, organization=creation.organization)
        DataArray.objects.create(level=level, dataset=dataset, coordinate_system=array_system, shape=shape, chunk_shape=shape)
        if level == 0:
            continue
        graph_logic.create_pixel_axes(array_system, axes)
        graph_logic.create_level_edge(
            array_system=array_system,
            intrinsic=intrinsic,
            shape_0=shapes[0],
            shape_level=shape,
            axis_specs=axis_specs,
            ctx=creation,
        )

    if value_unit is not None:
        anchor = CoordinateAnchor.objects.create(dataset=dataset, coordinates={})
        ValueUnit.objects.create(anchor=anchor, unit=value_unit)

    return dataset


async def create_array_dataset(
    ctx: HttpContext,
    name: str = "ArrayDataset",
    axes: list | None = None,
    shapes: list[list[int]] | None = None,
    *,
    system: CoordinateSystem | None = None,
    value_unit: str | None = None,
    folder: Folder | None = None,
) -> ArrayDataset:
    """An array dataset with a full coordinate graph. Defaults to mikro's 3x64x64 single-level c/y/x dataset."""
    return await sync_to_async(_seed_array_dataset_sync)(ctx, name, axes or SIMPLE_AXES, shapes or [[3, 64, 64]], system, value_unit, folder)


async def create_dataset(
    ctx: HttpContext,
    name: str = "Recording",
    axes: list | None = None,
    shape: list[int] | None = None,
    *,
    system: CoordinateSystem | None = None,
    value_unit: str | None = None,
    folder: Folder | None = None,
) -> ArrayDataset:
    """A single-level dataset, the ordinary ephys case. Defaults to a 1000-sample, 4-channel (t, c) recording."""
    return await create_array_dataset(ctx, name, axes or TC_AXES, [shape or [1000, 4]], system=system, value_unit=value_unit, folder=folder)


async def create_folder(ctx: HttpContext, name: str, **kwargs) -> Folder:
    return await Folder.objects.acreate(
        name=name,
        creator=kwargs.pop("creator", ctx.request.user),
        organization=ctx.request.organization,
        membership=kwargs.pop("membership", ctx.request.membership),
        **kwargs,
    )


async def create_file(ctx: HttpContext, name: str, folder: Folder | None = None, **kwargs) -> File:
    return await File.objects.acreate(
        name=name,
        folder=folder,
        creator=kwargs.pop("creator", ctx.request.user),
        organization=ctx.request.organization,
        membership=kwargs.pop("membership", ctx.request.membership),
        **kwargs,
    )


def _seed_physical_space_sync(
    ctx: HttpContext,
    dataset: ArrayDataset,
    axes: list,
    scale: list | None,
    translation: list | None,
    affine: list | None,
    name: str,
) -> CoordinateSystem:
    # The exact path `createCoordinateSystem` runs: a physical space is an ordinary space
    # plus one registration edge, and the transform member IS the kind -- there is no
    # scale+translation sugar (express that as one AFFINE matrix). INFERRED, because a
    # seeded sampling period stands in for numbers read from acquisition metadata.
    if affine is not None:
        transform = AffineTransformInputModel(affine=affine)
    elif scale is not None:
        transform = ScaleTransformInputModel(scale=scale)
    else:
        transform = TranslationTransformInputModel(translation=translation)
    spec = RegistrationPathInputModel(
        transform=transform,
        validity=enums.PlacementValidity.INFERRED,
    )
    return coordinate_system_logic.create_coordinate_system(
        name=f"{dataset.name}/{name}",
        axes=axes,
        registrations=[(dataset.coordinate_system, None, spec)],
        ctx=_creation(ctx),
    )


async def create_physical_space(
    ctx: HttpContext,
    dataset: ArrayDataset,
    axes: list,
    scale: list | None = None,
    translation: list | None = None,
    affine: list | None = None,
    name: str = "physical",
) -> CoordinateSystem:
    """A unit-carrying space for a dataset, plus the edge mapping its sample grid into it."""
    return await sync_to_async(_seed_physical_space_sync)(ctx, dataset, axes, scale, translation, affine, name)


async def create_lens(ctx: HttpContext, dataset: ArrayDataset, slices: list | None = None) -> Lens:
    """A lens over a dataset, through the same writer `createLens` uses."""
    from core.base_models.slices import SliceInputModel

    models_ = [entry if isinstance(entry, SliceInputModel) else SliceInputModel(**entry) for entry in (slices or [])]
    return await sync_to_async(coordinate_system_logic.create_lens)(dataset, models_, _creation(ctx))


def _seed_world_sync(ctx: HttpContext, name: str, axes: list, epoch) -> CoordinateSystem:  # noqa: ANN001 - datetime | None
    return coordinate_system_logic.create_world_space(name=f"{name}/world", axes=axes, epoch=epoch, ctx=_creation(ctx))


async def create_world(ctx: HttpContext, name: str = "World", axes: list | None = None, epoch=None) -> CoordinateSystem:  # noqa: ANN001
    """An ownerless shared space. Defaults to a clock in seconds."""
    return await sync_to_async(_seed_world_sync)(ctx, name, axes or CLOCK_AXES, epoch)


def _register_into_world_sync(ctx: HttpContext, world: CoordinateSystem, source: CoordinateSystem):
    """One explicit MANUAL registration: the identity on the axis names shared with the world.

    Nothing fabricates a placement, so a test that wants a placed source authors the
    registration first -- exactly the step a real client takes.
    """
    world_names = [axis.name for axis in world.axes.all()]
    shared = [axis.name for axis in source.axes.all() if axis.name in world_names]
    return graph_logic.create_identity_registration(
        input_system=source,
        world=world,
        shared=shared,
        name=f"{source.name} -> {world.name}",
        validity=enums.PlacementValidityChoices.MANUAL.value,
        ctx=_creation(ctx),
    )


async def register_into_world(ctx: HttpContext, world: CoordinateSystem, dataset: ArrayDataset | None = None, *, system: CoordinateSystem | None = None):
    """Register a dataset's sample grid (or an explicit system) into a world."""
    source = system if system is not None else await sync_to_async(lambda: dataset.coordinate_system)()
    return await sync_to_async(_register_into_world_sync)(ctx, world, source)


# --- tables and sparse matrices -----------------------------------------------------------------
#
# The ORM mirror of `createTableDataset` / `createSparseDataset`, for tests about the graph, the
# layers and the folder tree rather than about the bytes: a store row with no object behind it,
# the dataset in a space of its own, the declared columns (or the matrix's axes) as its axes.

#: A spike raster's axes: one INDEX axis enumerating the units, one TIME axis of samples.
RASTER_AXES = [
    axis("unit", enums.AxisType.INDEX),
    axis("t", enums.AxisType.TIME),
]


def _seed_table_dataset_sync(ctx: HttpContext, name: str, columns: list[dict], folder: Folder | None) -> "TableDataset":
    from core.models import Column, TableDataset
    from datalayer.models import ParquetStore

    store = ParquetStore.objects.create(organization=ctx.request.organization, key=f"seed-{name}", bucket="parquet", populated=True)
    system = CoordinateSystem.objects.create(name=f"{name}/table", creator=ctx.request.user, organization=ctx.request.organization)
    table = TableDataset.objects.create(name=name, store=store, coordinate_system=system, folder=folder, creator=ctx.request.user, organization=ctx.request.organization)
    axis_columns = []
    for index, column in enumerate(columns):
        axis_type = column.get("axis_type")
        Column.objects.create(
            table=table,
            order=index,
            name=column["name"],
            dtype=column.get("dtype", "DOUBLE"),
            role=enums.ColumnRoleChoices.COORDINATE.value if axis_type else column.get("role", enums.ColumnRoleChoices.ATTRIBUTE.value),
            axis_type=axis_type.value if axis_type else None,
            unit=column.get("unit"),
            references=column.get("references"),
        )
        if axis_type:
            axis_columns.append(column)
    if axis_columns:
        graph_logic.create_table_axes(
            system,
            [
                type("Col", (), {"name": c["name"], "axis_type": c["axis_type"], "unit": c.get("unit"), "long_name": None, "description": None})()
                for c in axis_columns
            ],
        )
    else:
        graph_logic.create_pixel_axes(system, [axis("object", enums.AxisType.INDEX)])
    return table


async def create_table_dataset(ctx: HttpContext, name: str = "Events", columns: list[dict] | None = None, folder: Folder | None = None) -> "TableDataset":
    """A table dataset, ORM-built. Defaults to an event table: a TIME column in seconds and a label.

    ``columns`` are dicts with ``name`` and optionally ``axis_type`` (an ``enums.AxisType``, which
    makes the column an axis), ``role``, ``unit``, ``dtype`` and ``references`` (a table).
    """
    columns = columns if columns is not None else [
        {"name": "t", "axis_type": enums.AxisType.TIME, "unit": "second"},
        {"name": "label", "role": enums.ColumnRoleChoices.LABEL.value, "dtype": "VARCHAR"},
    ]
    return await sync_to_async(_seed_table_dataset_sync)(ctx, name, columns, folder)


def _seed_sparse_dataset_sync(ctx: HttpContext, name: str, axes: list, shape: list[int], units: "TableDataset | None", folder: Folder | None) -> "SparseDataset":
    from core.models import SparseArray, SparseAxisReference, SparseDataset
    from datalayer.models import SparseStore

    store = SparseStore.objects.create(organization=ctx.request.organization, key=f"seed-{name}", bucket="zarr", populated=True, spec="1", shape=shape, layouts=[{"path": "layouts/axis0", "encoding": "csr_matrix", "indexed_axis": 0, "index_order": [1], "nnz": 0, "dtype": "float32"}])
    system = CoordinateSystem.objects.create(name=f"{name}/sparse", creator=ctx.request.user, organization=ctx.request.organization)
    dataset = SparseDataset.objects.create(name=name, coordinate_system=system, folder=folder, creator=ctx.request.user, organization=ctx.request.organization)
    graph_logic.create_pixel_axes(system, axes)
    SparseArray.objects.create(dataset=dataset, store=store, path="layouts/axis0", indexed_axis=0)
    if units is not None:
        SparseAxisReference.objects.create(dataset=dataset, axis=axes[0].name, references=units)
    return dataset


async def create_sparse_dataset(ctx: HttpContext, name: str = "Raster", axes: list | None = None, shape: list[int] | None = None, units: "TableDataset | None" = None, folder: Folder | None = None) -> "SparseDataset":
    """A sparse dataset, ORM-built. Defaults to a spike raster: (unit, t), 8 units by 30 000 samples."""
    return await sync_to_async(_seed_sparse_dataset_sync)(ctx, name, axes or RASTER_AXES, shape or [8, 30000], units, folder)


def _seed_clock_sync(ctx: HttpContext, name: str, unit: str, epoch) -> CoordinateSystem:  # noqa: ANN001 - datetime | None
    from core.logic import clocks

    return clocks.create_clock(name=name, unit=unit, epoch=epoch, ctx=_creation(ctx))


async def create_clock(ctx: HttpContext, name: str = "clock", unit: str = "second", epoch=None) -> CoordinateSystem:  # noqa: ANN001
    """A clock: one TIME axis in ``unit``, optionally anchored to a wall-clock epoch. A session's clock."""
    return await sync_to_async(_seed_clock_sync)(ctx, name, unit, epoch)


def _sampling_law_sync(ctx: HttpContext, grid: CoordinateSystem, clock: CoordinateSystem, rate: str, t_start: str):
    from kanne_server import scalars as quantities

    from core.logic import clocks

    rate_value = quantities.SCALAR_MAP[quantities.Frequency].parse_value(rate)
    start_value = quantities.SCALAR_MAP[quantities.Duration].parse_value(t_start)
    return clocks.write_sampling_law(grid=grid, clock=clock, sampling_rate=rate_value, t_start=start_value, ctx=_creation(ctx))


async def time_on(ctx: HttpContext, grid: CoordinateSystem, clock: CoordinateSystem, rate: str = "30 kHz", t_start: str = "0 s"):  # noqa: ANN201
    """Time a grid's samples on a clock with a sampling law."""
    return await sync_to_async(_sampling_law_sync)(ctx, grid, clock, rate, t_start)


def _offset_sync(ctx: HttpContext, source: CoordinateSystem, target: CoordinateSystem, offset: str):
    from kanne_server import scalars as quantities

    from core.logic import clocks

    return clocks.write_offset(source=source, target=target, offset=quantities.SCALAR_MAP[quantities.Duration].parse_value(offset), ctx=_creation(ctx))


async def offset_onto(ctx: HttpContext, source: CoordinateSystem, target: CoordinateSystem, offset: str = "0 s"):  # noqa: ANN201
    """Place one clock (or an event table's space) on another with an offset edge."""
    return await sync_to_async(_offset_sync)(ctx, source, target, offset)


# --- vendored from mikro's tests/seed.py: stores and declarations for createTableDataset / createSparseDataset


def _seed_parquet_store_sync(ctx: HttpContext, *, key: str, columns: list[tuple[str, str]] | None = None, populated: bool = True):
    """A parquet store carrying what `fill_info` would have read off the file.

    The same move `_seed_fabriks_store_sync` makes, and now necessary for the same reason: since
    `ParquetStore.fill_info` DESCRIBEs the object, a store left unpopulated makes
    `createTableDataset` reach for an S3 no unit test has. Before that it read nothing, so an
    unfinished store cost nothing and every test here left one behind.

    `columns=None` records a finished store whose schema was not worth stating -- which is most
    tests, because they are about placement and edges rather than about the file. Pass the pairs
    when the test is about the schema itself.
    """
    from datalayer.models import ParquetStore

    return ParquetStore.objects.create(
        path=f"s3://parquet/{key}",
        bucket="parquet",
        key=key,
        organization=ctx.request.organization,
        populated=populated,
        columns=[{"name": name, "type": dtype, "nullable": True} for name, dtype in columns] if columns is not None else None,
    )


async def create_parquet_store(ctx: HttpContext, *, key: str, columns: list[tuple[str, str]] | None = None, populated: bool = True):
    """A finished parquet store, ready to be registered as a table dataset."""
    return await sync_to_async(_seed_parquet_store_sync)(ctx, key=key, columns=columns, populated=populated)


def index_axis(columns: list[dict]) -> str:
    """The single INDEX coordinate column -- the one a keying source lands on.

    A source keys by supplying ids, and an id is looked up in an enumeration, so the axis it
    produces is the INDEX one. Derived rather than named at each call site: it is a fact about
    the column declaration, and the tests that migrated off `keyedBy` were all naming it by
    hand from the same three fixtures.
    """
    index = [c["name"] for c in columns if c.get("role") == "COORDINATE" and c.get("axisType") == "INDEX"]
    if len(index) != 1:
        raise AssertionError(f"expected exactly one INDEX coordinate column, got {index}")
    return index[0]


def flat_columns(
    columns: list[dict],
    *,
    identified_by: dict[str, list] | None = None,
    keyed_by: list | None = None,
) -> list[dict]:
    """The one `columns` list `createTableDataset` takes, from a fixture's column dicts.

    The fixtures were already flat -- one dict per column with a per-column ``axisType`` --
    and the old helpers existed only to SPLIT them into the two wire lists the API used to
    want. The wire is flat now too (axis-ness is `axisType` on the column, identification is
    `identifiedBy`, the old `references` field is a TABLE identification), so this is nearly
    the identity: the legacy ``role: COORDINATE`` marker becomes the bare ``axisType``, and a
    legacy ``references`` becomes ``identifiedBy: [{kind: TABLE}]``.

    ``identified_by`` names sources per column; ``keyed_by`` is the shorthand for the common
    case, putting them on the single INDEX axis. Columns named in neither get no
    ``identifiedBy``, which is legal and ordinary (a localization table's `x` axis is
    identified by nothing).
    """
    sources = dict(identified_by or {})
    if keyed_by:
        # The convenience the migration off `keyedBy` needed: put these sources on the axis a
        # keying source produces, which is the INDEX one.
        sources.setdefault(index_axis(columns), keyed_by)

    declared = []
    for column in columns:
        entry: dict = {"name": column["name"], "dtype": column.get("dtype", "DOUBLE")}
        if column.get("role") == "COORDINATE":
            # COORDINATE is not a role the wire may claim: it follows from `axisType`.
            entry["axisType"] = column["axisType"]
        elif column.get("role") is not None:
            entry["role"] = column["role"]
        for key in ("unit", "longName", "description"):
            if column.get(key) is not None:
                entry[key] = column[key]
        identifications = list(sources.get(column["name"], []))
        if column.get("references") is not None:
            # The retired field, spelled the one remaining way.
            identifications.append({"kind": "TABLE", "table": column["references"]})
        if identifications:
            entry["identifiedBy"] = identifications
        declared.append(entry)
    return declared


def split_declaration(columns: list[dict]) -> tuple[list[tuple[str, str]], list[dict]]:
    """The store's schema and the wire's column list, from one fixture constant.

    Named for the split it used to perform into `axes` + `columns`; what survives of the
    split is the one real division left -- the file's own account (``store_columns``, what
    ``fill_info`` records) versus the declaration checked against it.

    Returns:
        ``(store_columns, columns)`` -- the store's `[(name, duckdb type)]` in file order,
        and the flat `ColumnInput` dicts in the same order.
    """
    store_columns = [(column["name"], column.get("dtype", "DOUBLE")) for column in columns]
    return store_columns, flat_columns(columns)


async def table_input(
    ctx: HttpContext,
    name: str,
    columns: list[dict],
    *,
    identified_by: dict[str, list] | None = None,
    keyed_by: list | None = None,
    **extra: object,
) -> dict:
    """Everything `createTableDataset` needs, from one fixture-shaped column list.

    The mutation reads a column's name and type off the **file** and takes only what the file
    cannot say, so a test's one constant becomes two things: the store's own schema and the
    flat declaration. This also creates the store carrying that schema, which is load-bearing
    -- `columns_for_store` reads it on every create, and a store without it makes the create
    reach for an S3 no unit test has.
    """
    store_columns = [(column["name"], column.get("dtype", "DOUBLE")) for column in columns]
    # Unique, because two tables of the same name in one test are ordinary and the store path
    # is unique-constrained.
    store = await create_parquet_store(ctx, key=f"{name.replace(' ', '-')}-{uuid.uuid4().hex[:8]}", columns=store_columns)
    return {
        "name": name,
        "data": str(store.pk),
        "columns": flat_columns(columns, identified_by=identified_by, keyed_by=keyed_by),
        **extra,
    }


def split_payload(columns: list[dict], *, identified_by: dict[str, list] | None = None, keyed_by: list | None = None) -> dict:
    """The `columns` half of a create payload, for a test that builds its store itself.

    :func:`table_input` is the whole payload and creates the store; this is the same shape for
    the call sites that already have a store in hand. The store still has to carry the file's
    schema -- see :func:`create_parquet_store` -- or the create has nothing to infer from.
    """
    return {"columns": flat_columns(columns, identified_by=identified_by, keyed_by=keyed_by)}


def sparse_layout(axis: int, rank: int = 2, nnz: int = 96) -> dict:
    """One entry of a sparse store's `layouts`, as `finishSparseUpload` would have recorded it."""
    return {
        "path": sparse_layout_path(axis),
        "encoding": ("csr_matrix" if axis == 0 else "csc_matrix") if rank == 2 else "csr_matrix",
        "encoding_version": "0.1.0",
        "indexed_axis": axis,
        "index_order": [other for other in range(rank) if other != axis],
        "nnz": nnz,
        "dtype": "float32",
        "chunks": {"data": 32768, "indices": 32768, "indptr": 32768},
        "range_readable": False,
    }


async def create_sparse_store(ctx: HttpContext, key: str, *, axes: tuple[int, ...] = (0,), shape: list[int]) -> SparseStore:
    """A finished sparse store holding a layout per axis in ``axes``, built directly.

    **One matrix is one upload**, so a store is a whole matrix in one or more layouts rather than
    one layout apiece. `fill_info` reads the prefix off S3; setting the fields here says the same
    thing more plainly, and what is on trial is what a mutation does with a store's declared facts.
    """
    extents = list(shape)
    return await sync_to_async(SparseStore.objects.create)(
        path=f"s3://zarr/{key}",
        bucket="zarr",
        key=key,
        organization=ctx.request.organization,
        populated=True,
        spec="1",
        shape=extents,
        layouts=[sparse_layout(axis, rank=len(extents)) for axis in axes],
    )
