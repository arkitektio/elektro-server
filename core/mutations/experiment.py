"""Creating an experiment: recordings and stimuli, laid out on one timeline.

An experiment is mikro's scene, over time: it composes views over a ``world`` it adopts and
never owns, and a view is a lens shown in it. What this module owns is the *lowering* -- a
client still says what it always said, "show this recording, 50 ms in, for 200 ms", and that
is written as what it is:

* ``offset`` is **one edge per clock**, from the simulation's clock into the world. It used
  to be a column on every view, which let a stimulus view and a recording view of *one*
  simulation state two offsets and silently misalign stimulus and response. Every dataset of a
  run shares the run's clock, so they move together or not at all; two views of one
  simulation stating different offsets is refused, by name.
* ``window`` is **a lens**: the samples between two instants on the recording's own clock,
  found by inverting its sampling law. Only a sampling law can be inverted in closed form,
  so a window over a run timed by a lookup (a variable time step) is refused rather than
  guessed at -- pass an existing ``lens`` cut in sample indices instead.

Nothing fabricates a placement. A view whose data has no route into the world is refused
with the way to give it one, exactly as mikro refuses a layer -- with one deliberate
difference: the route need not be *affine*. A run timed by a lookup reaches the world across
a FIELD, which no single matrix expresses, and mikro's gate (rfc10) would refuse to show it.
A timeline can draw samples at looked-up instants without a matrix, so it is admitted;
``asAffine`` on such a view says why it has none.
"""

import strawberry
from django.db import transaction
from kante.types import Info
from pydantic import BaseModel, model_validator

import kante
from kanne_server import scalars as quantities

from core import enums, models, types
from core.base_models.slices import SliceInputModel
from core.creation import CreationContext
from core.logic import clocks
from core.logic import coordinate_system as coordinate_system_logic
from core.logic import graph as graph_logic
from core.scoping import get_for_org


class WindowInputModel(BaseModel):
    start: int | None = None
    stop: int | None = None


@kante.pydantic_input(WindowInputModel, description="A stretch of time on the source's OWN clock, e.g. the first 200 ms of a run. Lowered to a lens by inverting the sampling law, so it needs one")
class WindowInput:
    """A time window over a recording or stimulus."""

    start: quantities.Duration | None = strawberry.field(default=None, description="The first instant shown, on the source's own clock. Omit to start at the first sample")
    stop: quantities.Duration | None = strawberry.field(default=None, description="The instant the view stops before, on the source's own clock. Omit to run to the last sample")


class ViewInputBase(BaseModel):
    offset: int | None = None
    window: WindowInputModel | None = None
    lens: str | None = None
    label: str | None = None
    visible: bool = True

    @model_validator(mode="after")
    def _one_selection(self) -> "ViewInputBase":
        if self.window is not None and self.lens is not None:
            raise ValueError("A view shows one selection: pass `window` (a stretch of time, lowered to a lens for you) or `lens` (one you already cut), not both.")
        return self


class RecordingViewInputModel(ViewInputBase):
    recording: str


class StimulusViewInputModel(ViewInputBase):
    stimulus: str


_OFFSET = (
    "Where the source's clock sits on the experiment's timeline: its zero is this far into the world. Written as ONE edge from the simulation's clock into the world, "
    "shared by every view of that simulation -- so two views of one simulation must agree on it. Omit it when that clock is already related to the world"
)
_WINDOW = "Show only a stretch of time, given on the source's own clock. Lowered to a sliced lens. Needs a sampling law: a run timed by `timeDataset` has no closed-form inverse, so cut a `lens` in sample indices instead"
_LENS = "Show an existing lens over the source's dataset, instead of `window`. Omit both to show everything"


@kante.pydantic_input(RecordingViewInputModel, description="A recording to show in an experiment: which one, where it sits on the timeline, and how much of it")
class RecordingViewInput:
    """A recording view of an experiment."""

    recording: strawberry.ID
    offset: quantities.Duration | None = strawberry.field(default=None, description=_OFFSET)
    window: WindowInput | None = strawberry.field(default=None, description=_WINDOW)
    lens: strawberry.ID | None = strawberry.field(default=None, description=_LENS)
    label: str | None = None
    visible: bool = True


@kante.pydantic_input(StimulusViewInputModel, description="A stimulus to show in an experiment: which one, where it sits on the timeline, and how much of it")
class StimulusViewInput:
    """A stimulus view of an experiment."""

    stimulus: strawberry.ID
    offset: quantities.Duration | None = strawberry.field(default=None, description=_OFFSET)
    window: WindowInput | None = strawberry.field(default=None, description=_WINDOW)
    lens: strawberry.ID | None = strawberry.field(default=None, description=_LENS)
    label: str | None = None
    visible: bool = True


class CreateExperimentInputModel(BaseModel):
    name: str
    description: str | None = None
    world: str | None = None
    stimulus_views: list[StimulusViewInputModel] = []
    recording_views: list[RecordingViewInputModel] = []


@kante.pydantic_input(CreateExperimentInputModel, description="An experiment: recordings and stimuli laid out on one timeline")
class CreateExperimentInput:
    """Input for creating an experiment."""

    name: str
    description: str | None = None
    world: strawberry.ID | None = strawberry.field(
        default=None,
        description="The coordinate system to compose over: an existing shared space, adopted and never owned. Omit it and the experiment gets a fresh timeline -- a clock in seconds with no epoch, because trial-aligned time has no wall clock",
    )
    stimulus_views: list[StimulusViewInput] = strawberry.field(default_factory=list)
    recording_views: list[RecordingViewInput] = strawberry.field(default_factory=list)


def _lens_for(view: ViewInputBase, site, info: Info, ctx: CreationContext) -> "models.Lens":  # noqa: ANN001 - a Recording or Stimulus
    """The lens a view shows: the one named, the one a window lowers to, or the whole dataset."""
    dataset = site.dataset
    if dataset.coordinate_system_id is None:
        raise ValueError(f"'{site.display_label}' has a dataset that is not in the coordinate graph (it was created without axes), so it cannot be placed on a timeline.")

    if view.lens is not None:
        lens = get_for_org(models.Lens, info, id=view.lens)
        if lens.dataset_id != dataset.pk:
            raise ValueError(f"Lens {lens.pk} selects over dataset {lens.dataset_id}, but '{site.display_label}' is dataset {dataset.pk}. A view shows a selection of its own source.")
        return lens

    if view.window is None or (view.window.start is None and view.window.stop is None):
        # Everything. Reused rather than re-minted: an unsliced lens owns no space, so a second
        # one would be a second row saying nothing the first did not.
        return models.Lens.objects.filter(dataset=dataset, slices=[]).order_by("pk").first() or coordinate_system_logic.create_lens(dataset, [], ctx)

    rate, t_start = clocks.sampling_of(dataset.coordinate_system, site.simulation.clock)
    if rate is None:
        raise ValueError(
            f"A `window` is a stretch of time, found by inverting the sampling law -- but '{site.display_label}' is timed by a lookup (its run had a variable time step), "
            "which has no closed-form inverse. Cut a lens in sample indices with createLens and pass it as `lens`."
        )
    sample_axis = clocks.time_axis(dataset.coordinate_system)
    size = dataset.shape_list[dataset.axis_names.index(sample_axis.name)]

    def sample_at(instant: int | None, default: int) -> int:
        if instant is None:
            return default
        # picoseconds -> samples: (t - t_start) * rate, with the rate in nanohertz.
        return max(0, min(size, round((instant - t_start) * rate / 1e21)))

    start, stop = sample_at(view.window.start, 0), sample_at(view.window.stop, size)
    if stop <= start:
        raise ValueError(f"The window over '{site.display_label}' selects no samples: it runs from sample {start} to sample {stop} of {size}.")
    return coordinate_system_logic.create_lens(dataset, [SliceInputModel(axis=sample_axis.name, start=start, stop=stop)], ctx)


def _place(view: ViewInputBase, site, world: "models.CoordinateSystem", stated: dict, ctx: CreationContext) -> None:  # noqa: ANN001
    """State where a view's clock sits in the world -- once per clock, and refuse a second, different, statement."""
    clock = site.simulation.clock
    if view.offset is None:
        return

    if clock.pk in stated:
        previous_offset, previous_label = stated[clock.pk]
        if previous_offset != view.offset:
            raise ValueError(
                f"'{site.display_label}' and '{previous_label}' are timed against the same clock ('{clock.name}') but state different offsets. "
                "Every dataset of one simulation shares its clock, so they sit on the timeline together: share one offset. "
                "To show one source at two offsets, lay a second simulation's clock into the world, or register a lens of it with createTransformation."
            )
        return

    existing = clocks.offset_of(clock, world)
    if existing is not None and existing != view.offset:
        raise ValueError(
            f"'{clock.name}' already sits in '{world.name}', at a different offset than '{site.display_label}' states. "
            "That edge is shared by everything over this world; refine it with updateTransformation rather than stating a second one, which would be a rival."
        )
    if existing is None:
        clocks.write_offset(source=clock, target=world, offset=view.offset, name=f"{clock.name} -> {world.name}", validity=enums.PlacementValidity.MANUAL, ctx=ctx)
    stated[clock.pk] = (view.offset, site.display_label)


def _assert_reaches(lens: "models.Lens", site, world: "models.CoordinateSystem") -> None:  # noqa: ANN001
    """Refuse a view whose data has no route into the world. Deliberately looser than mikro's gate: a FIELD route counts."""
    if graph_logic.is_placeable_in(world, lens.space, require_affine=False):
        return
    raise ValueError(
        f"Nothing relates '{site.display_label}' to '{world.name}', so there is nowhere on this timeline to show it. "
        "State its `offset`, or relate its simulation's clock to the world with createTransformation first. Nothing is placed by default: an assumed offset of zero cannot be told from a measured one."
    )


def create_experiment(info: Info, input: CreateExperimentInput) -> types.Experiment:
    """Create an experiment over a world, and lower each view to a lens and its clock's offset to one edge."""
    parsed = input.to_pydantic()
    ctx = CreationContext.from_info(info)

    with transaction.atomic():
        world = get_for_org(models.CoordinateSystem, info, id=parsed.world) if parsed.world else coordinate_system_logic.create_world_space(name=f"{parsed.name}/world", ctx=ctx)
        if clocks.time_axis(world) is None:
            raise ValueError(f"'{world.name}' has no TIME axis, so it is not something recordings can be laid out along.")

        experiment = models.Experiment.objects.create(
            name=parsed.name,
            description=parsed.description,
            creator=info.context.request.user,
            organization=info.context.request.organization,
            world=world,
        )

        stated: dict[int, tuple[int, str]] = {}
        order = 0
        for view_model, site_model, field, views in (
            (models.ExperimentRecordingView, models.Recording, "recording", parsed.recording_views),
            (models.ExperimentStimulusView, models.Stimulus, "stimulus", parsed.stimulus_views),
        ):
            for view in views:
                site = get_for_org(site_model, info, id=getattr(view, field))
                _place(view, site, world, stated, ctx)
                lens = _lens_for(view, site, info, ctx)
                _assert_reaches(lens, site, world)
                view_model.objects.create(experiment=experiment, lens=lens, label=view.label, visible=view.visible, order=order, **{field: site})
                order += 1

    return experiment
