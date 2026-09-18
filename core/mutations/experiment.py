"""Creating, updating and deleting experiments: mikro's scene mutations, over time.

An experiment composes :class:`~core.models.ExperimentLayer` rows over a ``world`` it adopts and
never owns. Two ways to make one, as in mikro:

* ``createExperiment`` -- an empty composition over a world you name (``coordinateSystem``) or
  one minted for you (a clock in seconds, no epoch), which the layer mutations then fill;
* ``createExperimentFromCoordinateSystem`` -- **CS-first**: point it at a clock that data is
  already timed on (a session's, a run's) and it materializes a layer for everything laid out
  on it (:func:`core.logic.experiment.bootstrap_experiment_from_system`). Authors no edges.

Neither takes an ``offset``. Where a clock sits on another is a fact about the two clocks,
shared by everything timed on them, and it is stated once with ``createClockOffset`` -- a
per-layer offset is how two views of one run once came to disagree about when it started.
"""

import datetime

import strawberry
from django.db import transaction
from kante.types import Info
from pydantic import BaseModel

import kante

from core import models, types
from core.creation import CreationContext
from core.inputs.coords import PhysicalAxisInput, PhysicalAxisInputModel
from core.logic import experiment as experiment_logic
from core.scoping import get_for_org


class CreateExperimentInputModel(BaseModel):
    name: str
    description: str | None = None
    coordinate_system: str | None = None
    axes: list[PhysicalAxisInputModel] | None = None
    epoch: datetime.datetime | None = None


@kante.pydantic_input(
    CreateExperimentInputModel,
    description="An empty experiment over a world: an existing space it adopts (`coordinateSystem`), or one minted for it. Fill it with the layer mutations. mikro's createScene",
)
class CreateExperimentInput:
    """Input for creating an experiment."""

    name: str
    description: str | None = None
    coordinate_system: strawberry.ID | None = strawberry.field(
        default=None,
        description="The coordinate system to compose over: an existing space with a TIME axis, adopted and never owned. A session's clock is the usual choice. Omit it and a world is minted",
    )
    axes: list[PhysicalAxisInput] | None = strawberry.field(
        default=None,
        description="(minted world only) The axes of the world to mint. Omit for one TIME axis in seconds -- every dataset here is a signal over time, so time is the one axis two recordings share",
    )
    epoch: datetime.datetime | None = strawberry.field(default=None, description="(minted world only) The wall-clock instant the world's zero is. Omit for trial-aligned time, which has no wall clock")


def create_experiment(info: Info, input: CreateExperimentInput) -> types.Experiment:
    """Create an empty experiment over a world."""
    parsed = input.to_pydantic()
    ctx = CreationContext.from_info(info)
    world = get_for_org(models.CoordinateSystem, info, id=parsed.coordinate_system) if parsed.coordinate_system else None
    with transaction.atomic():
        return experiment_logic.create_experiment(name=parsed.name, description=parsed.description, world=world, axes=parsed.axes, epoch=parsed.epoch, ctx=ctx)


class ExperimentPolicyInputModel(BaseModel):
    nchildren: int = 32
    include_traces: bool = True
    include_spikes: bool = True
    include_events: bool = True
    include_annotations: bool = True
    skip_unplaceable: bool = False


@kante.pydantic_input(ExperimentPolicyInputModel, description="What `createExperimentFromCoordinateSystem` stages. mikro's ScenePolicyInput, for time series")
class ExperimentPolicyInput:
    """What a bootstrap stages."""

    nchildren: int = strawberry.field(default=32, description="The most layers to create. Sources are taken in layer order: traces, spikes, events, annotations, each oldest first")
    include_traces: bool = strawberry.field(default=True, description="Draw every array dataset with a TIME axis as a TRACE over its whole-dataset lens. Times datasets (a lookup's map) are never drawn")
    include_spikes: bool = strawberry.field(default=True, description="Draw every sparse dataset with a TIME axis (a spike raster) as SPIKES")
    include_events: bool = strawberry.field(default=True, description="Draw every table with a TIME coordinate column as EVENTS")
    include_annotations: bool = strawberry.field(default=True, description="Draw every annotation collection as ANNOTATION")
    skip_unplaceable: bool = strawberry.field(default=False, description="Leave out a source with no route to the world instead of refusing the whole experiment")


class CreateExperimentFromCoordinateSystemInputModel(BaseModel):
    coordinate_system: str
    name: str | None = None
    policy: ExperimentPolicyInputModel = ExperimentPolicyInputModel()


@kante.pydantic_input(
    CreateExperimentFromCoordinateSystemInputModel,
    description=(
        "Stage what is already laid out on a coordinate system as an experiment over it: a layer for every trace, spike raster, event table and annotation collection that reaches "
        "it -- through a sampling law, a time lookup, or a chain of clock offsets. CS-first: time the data on a clock, then point this at the clock. Authors no edges. "
        "mikro's createSceneFromCoordinateSystem"
    ),
)
class CreateExperimentFromCoordinateSystemInput:
    """Input for bootstrapping an experiment over an existing space."""

    coordinate_system: strawberry.ID = strawberry.field(description="The space to compose over and stage from: a session's clock, a run's clock, a world. Adopted, never owned")
    name: str | None = strawberry.field(default=None, description="The experiment's name. Defaults to the space's")
    policy: ExperimentPolicyInput | None = strawberry.field(default=None, description="What to stage. Omit for everything")


def create_experiment_from_coordinate_system(info: Info, input: CreateExperimentFromCoordinateSystemInput) -> types.Experiment:
    """Create an experiment over a space, with a layer for everything laid out on it."""
    parsed = input.to_pydantic()
    ctx = CreationContext.from_info(info)
    system = get_for_org(models.CoordinateSystem, info, id=parsed.coordinate_system)
    policy = experiment_logic.Policy(**(parsed.policy or ExperimentPolicyInputModel()).model_dump())
    return experiment_logic.bootstrap_experiment_from_system(system, name=parsed.name, policy=policy, ctx=ctx)


class UpdateExperimentInputModel(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None


@kante.pydantic_input(UpdateExperimentInputModel, description="Rename or redescribe an experiment. Its world is fixed: an experiment over another space is another experiment")
class UpdateExperimentInput:
    """Input for updating an experiment."""

    id: strawberry.ID
    name: str | None = None
    description: str | None = None


def update_experiment(info: Info, input: UpdateExperimentInput) -> types.Experiment:
    """Rename an experiment, or redescribe it."""
    parsed = input.to_pydantic()
    experiment = get_for_org(models.Experiment, info, id=parsed.id)
    if parsed.name is not None:
        experiment.name = parsed.name
    if parsed.description is not None:
        experiment.description = parsed.description
    experiment.save()
    return experiment
