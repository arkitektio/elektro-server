"""Shared builders for the coordinate-graph tests.

Ported from mikro's ``tests/seed.py``, which the vendored tests import by name. A world
stands where mikro seeds a scene.

Every helper creates rows in the organization and user of the supplied context (the
identity the static "test" token resolves to, see conftest.py). They are the ORM mirror
of the mutations, so a test about the graph does not have to go through GraphQL -- or
through an object store -- to get a well-formed dataset: a level carries its ``shape``
itself, which is all the graph ever reads of it, so no store is needed at all.
"""

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
