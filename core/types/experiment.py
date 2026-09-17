"""GraphQL types for an experiment and its views: mikro's Scene and Layer, over time.

The placement fields on a view -- ``pathToWorld``, ``asAffine``, ``placement``,
``placementValidity``, ``placementInvariance`` -- are vendored from mikro's ``Layer``
(``mikro/core/types/array_dataset.py``), descriptions and all. A view belongs to exactly one
experiment, so this is the one place "where does this data sit on the timeline" has a single
right answer; everything else about a space is asked of the space.
"""

import datetime
from typing import TYPE_CHECKING, Annotated, List, Optional, cast

import strawberry
import strawberry_django
from kante.types import Info
from koherent.strawberry.types import ProvenanceEntry
from strawberry import auto

from authentikate.strawberry.types import User
from kanne_server import scalars as quantities

from core import enums, filters, models
from core.inputs.coords import CoordinateInput, at_map
from core.logic import clocks, scene_graph
from core.types._shared import OrgScoped, build_prescoped_queryset
from core.types.annotation import AnnotationCollection
from core.types.array_dataset import Lens
from core.types.coords import AffinePlacement, CoordinateSystem, PlacementStep

if TYPE_CHECKING:
    # Only for the lazy annotations below: `core.types` imports this module, so importing
    # it back at runtime would be a cycle.
    from core.types import Recording, Stimulus


class _PlacedView(OrgScoped):
    """Tenant scoping plus the relations the placement logic reads off a view in Python.

    The optimizer cannot infer them: it prefetches what the *selection set* names, and a
    client asking only for ``pathToWorld`` never names ``lens``. The axes come as a
    ``prefetch_related`` because they are a reverse relation: ``asAffine`` reads the source
    system's axis order to label its matrix's columns.
    """

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):  # noqa: ANN001, ANN206 - strawberry_django's hook
        scoped = build_prescoped_queryset(info, queryset)
        return scoped.select_related(*scene_graph.LAYER_PLACEMENT_RELATIONS).prefetch_related(*scene_graph.LAYER_SOURCE_AXIS_PREFETCH)


@strawberry.interface(description="Something shown in an experiment -- a recording, a stimulus, a collection of annotations -- and where it sits on the experiment's timeline. It carries no time of its own: where it sits is derived from the coordinate graph, on read")
class ExperimentView:
    """What every view of an experiment shares: mikro's Layer."""

    id: strawberry.ID
    label: str | None
    order: int
    visible: bool
    experiment: Annotated["Experiment", strawberry.lazy("core.types.experiment")]

    @strawberry_django.field(
        description="The path of transformation edges from this view's source coordinate system to its experiment's world. A view belongs to exactly one experiment, so this is the one 'to world' question with a single right answer -- the path uses the dataset's own facts (its lens shift, its sampling law or time lookup) plus the world's registrations and the clocks chained into it. Null when the view is unregistered or has no source system; empty when the source already is the world. Every step is here in full, with its own validity, invariance and provenance, which is what to ask for when you care *how* the data got placed; `asAffine` is the same path composed, for when you only need the map",
    )
    def path_to_world(self, info: Info, at: List[CoordinateInput] | None = None) -> List[PlacementStep] | None:
        """The view's placement path, as (edge, inverted) steps."""
        steps = scene_graph.for_request(info, self.experiment).placement_path(self, at=at_map(at))
        if steps is None:
            return None
        return [PlacementStep(transformation=edge, inverted=inverted) for edge, inverted in steps]

    @strawberry_django.field(
        description=(
            "This view's whole `pathToWorld` composed into one affine map -- the same path, same edges, same order, with the flagged steps inverted. For a sampled recording it reads "
            "`t_world = sample * period + start`, the sampling law and every clock offset multiplied out. Derived on read and stored nowhere, exactly as the path itself is, so refining one "
            "edge moves it. **Null when `pathToWorld` is null.** It errors rather than returning null when a path exists but does not condense: a FIELD step gives its map as the values of "
            "an array and has no closed form -- which is every view over a spike train, an irregularly sampled signal, or a run with a variable time step -- and the error names the "
            "transformation that stopped it. `outputAxes` names only the destination axes the path constrains, so pass `strict: true` to be refused a partial map instead of handed one"
        ),
    )
    def as_affine(self, info: Info, strict: bool = False, at: List[CoordinateInput] | None = None) -> AffinePlacement | None:
        """The view's placement path composed into one labelled affine map."""
        condensed = scene_graph.for_request(info, self.experiment).condensed_placement(self, at=at_map(at))
        if condensed is None:
            return None

        if strict and not condensed.total:
            world = self.experiment.world
            world_axes = [axis.name for axis in world.axes.all()] if world else []
            missing = [axis for axis in world_axes if axis not in condensed.output_axes]
            raise ValueError(
                f"This view's placement does not constrain every axis of its experiment's world: it maps onto {condensed.output_axes} and says nothing about {missing}. "
                "That is an honest partial registration, not a failure -- drop `strict` to read the map over the axes it does name, or author a registration that places the data along the rest."
            )

        return AffinePlacement(matrix=condensed.matrix, input_axes=condensed.input_axes, output_axes=condensed.output_axes, total=condensed.total)

    @strawberry_django.field(
        description=(
            "Whether this view has a place on its experiment's timeline, and if not, why not. A null `pathToWorld` means three different things -- nobody has related this data's "
            "clock to the world, its correspondence did not survive the operation that produced it and it can never be placed, or it is registered per index and you have not said which "
            "index -- and a client should not have to guess which. UNREGISTERED is a gap to close; UNMAPPABLE is a fact to badge; CONDITIONAL is a placement to ask again for with `at`. "
            "Derived, never stored"
        ),
    )
    def placement(self, info: Info, at: List[CoordinateInput] | None = None) -> enums.PlacementState:
        """PLACED, CONDITIONAL, UNREGISTERED or UNMAPPABLE."""
        return enums.PlacementState(scene_graph.for_request(info, self.experiment).placement_state(self, at=at_map(at)))

    @strawberry_django.field(
        description=(
            "How much this view's placement is actually known: the weakest edge on its path to world. INFERRED when it rests on a sampling law read from metadata, MANUAL once someone "
            "authored an offset, VALIDATED once it was checked, UNKNOWN when there is no path at all. Derived, never stored -- and distinct from a single edge's `validity`: this is the "
            "minimum over the whole path"
        ),
    )
    def placement_validity(self, info: Info, at: List[CoordinateInput] | None = None) -> enums.PlacementValidity:
        """The weakest validity on the view's placement path."""
        return enums.PlacementValidity(scene_graph.for_request(info, self.experiment).placement_validity(self, at=at_map(at)))

    @strawberry_django.field(
        description=(
            "Which geometric properties survive the whole walk from this view's samples to its experiment's world: the weakest edge on its path. AFFINE or stronger means a duration "
            "measured in samples is a duration on the timeline up to one factor, and `asAffine` has an answer; DIFFEOMORPHIC means the path crosses a time lookup, so intervals between "
            "samples are not uniform and nothing metric transfers; NONE means there is no path at all. Derived, never stored"
        ),
    )
    def placement_invariance(self, info: Info, at: List[CoordinateInput] | None = None) -> enums.TransformInvariance:
        """The weakest invariance class on the view's placement path."""
        return enums.TransformInvariance(scene_graph.for_request(info, self.experiment).placement_invariance(self, at=at_map(at)))



@strawberry.interface(description="A view of a dataset -- a recording or a stimulus: the lens it shows, and the two readings of the graph a timeline asks for most, its offset and its duration")
class ExperimentLensView(ExperimentView):
    """What a recording view and a stimulus view share beyond every view."""

    lens: Lens = strawberry_django.field(description="The selection this view shows: a lens over the source's dataset. Unsliced when the view shows everything")

    @strawberry_django.field(
        description=(
            "Where this view's clock sits on the experiment's timeline. Derived: it is read off the ONE edge from the simulation's clock into the world, which every view of that "
            "simulation shares -- it used to be a column on each view, where two views of one run could disagree. Null when that edge is not a plain offset, or does not exist"
        ),
    )
    def offset(self, info: Info) -> quantities.Duration | None:
        """The offset of the source's clock in the world, read off the edge between them."""
        return clocks.offset_of(_site_of(self).simulation.clock, self.experiment.world)

    @strawberry_django.field(description="How much time this view shows. Derived from its lens' extent along the sample axis and the sampling law. Null when the source is timed by a lookup, where a sample count is not a duration")
    def duration(self, info: Info) -> quantities.Duration | None:
        """The shown extent along time: samples over rate."""
        site = _site_of(self)
        grid = site.dataset.coordinate_system
        rate, _ = clocks.sampling_of(grid, site.simulation.clock)
        sample_axis = clocks.time_axis(grid) if grid is not None else None
        if rate is None or sample_axis is None:
            return None
        samples = self.lens.get_size_of_axis(sample_axis.name)
        step = next((entry.step or 1 for entry in self.lens.slices_list if entry.axis == sample_axis.name), 1)
        # samples * step / rate, in picoseconds, with the rate in nanohertz.
        return int(round(samples * step * 1e21 / rate))


def _site_of(view):  # noqa: ANN001, ANN202 - a recording or stimulus view row
    """The recording or stimulus a view shows."""
    return view.recording if isinstance(view, models.ExperimentRecordingView) else view.stimulus


@strawberry_django.type(models.ExperimentRecordingView, filters=filters.ExperimentRecordingViewFilter, ordering=filters.ExperimentRecordingViewOrder, pagination=True)
class ExperimentRecordingView(ExperimentLensView, _PlacedView):
    """A recording, shown in an experiment."""

    id: auto
    label: str | None
    order: int
    visible: bool
    lens: Lens
    experiment: Annotated["Experiment", strawberry.lazy("core.types.experiment")]
    recording: Annotated["Recording", strawberry.lazy("core.types")]


@strawberry_django.type(models.ExperimentStimulusView, filters=filters.ExperimentStimulusViewFilter, ordering=filters.ExperimentStimulusViewOrder, pagination=True)
class ExperimentStimulusView(ExperimentLensView, _PlacedView):
    """A stimulus, shown in an experiment."""

    id: auto
    label: str | None
    order: int
    visible: bool
    lens: Lens
    experiment: Annotated["Experiment", strawberry.lazy("core.types.experiment")]
    stimulus: Annotated["Stimulus", strawberry.lazy("core.types")]


class _PlacedAnnotationView(OrgScoped):
    """The same, for a view whose data lives in an annotation collection's own space."""

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):  # noqa: ANN001, ANN206 - strawberry_django's hook
        scoped = build_prescoped_queryset(info, queryset)
        return scoped.select_related(*scene_graph.ANNOTATION_PLACEMENT_RELATIONS).prefetch_related(*scene_graph.ANNOTATION_SOURCE_AXIS_PREFETCH)


@strawberry_django.type(models.ExperimentAnnotationView, filters=filters.ExperimentAnnotationViewFilter, ordering=filters.ExperimentAnnotationViewOrder, pagination=True)
class ExperimentAnnotationView(ExperimentView, _PlacedAnnotationView):
    """An annotation collection, shown in an experiment. One view per collection: per-shape styling lives on the annotations themselves."""

    id: auto
    label: str | None
    order: int
    visible: bool
    experiment: Annotated["Experiment", strawberry.lazy("core.types.experiment")]
    collection: AnnotationCollection = strawberry_django.field(description="The annotation collection whose shapes this view shows. Its own coordinate system is the view's space, so `pathToWorld` says where a vertex of any of its annotations sits on the timeline")


@strawberry_django.type(models.Experiment, filters=filters.ExperimentFilter, ordering=filters.ExperimentOrder, pagination=True)
class Experiment(OrgScoped):
    """Recordings and stimuli laid out on one timeline. mikro's Scene, over time."""

    id: auto
    name: str
    description: str | None
    created_at: datetime.datetime
    creator: User | None
    recording_views: List[ExperimentRecordingView] = strawberry_django.field(description="The recordings shown in this experiment")
    stimulus_views: List[ExperimentStimulusView] = strawberry_django.field(description="The stimuli shown in this experiment")
    annotation_views: List[ExperimentAnnotationView] = strawberry_django.field(description="The annotation collections shown in this experiment")
    annotation_collection: Optional[AnnotationCollection] = strawberry_django.field(
        description="The collection minted as this experiment's own drawing surface by `createAnnotation(experiment:)`, or null before anything was drawn on it. Its shapes are in the world's coordinates"
    )
    provenance_entries: List[ProvenanceEntry] = strawberry_django.field()
    world: Optional[CoordinateSystem] = strawberry_django.field(
        description=(
            "The space this experiment composes over: its timeline. Adopted, never owned -- several experiments may share one, and deleting an experiment never deletes it. Ask it for "
            "`registrations` (the clocks laid into it), `placedSystems` and `inView(region:)`; ask a view for `pathToWorld`"
        )
    )

    @strawberry_django.field(description="Is this experiment pinned by the current user")
    def pinned(self, info: Info) -> bool:
        return cast(models.Experiment, self).pinned_by.filter(id=info.context.request.user.id).exists()
