"""Guarded delete mutations.

A single shared ``DeleteInput`` (an id) feeds a family of resolvers, one per
model that didn't already have a bespoke delete. Each resolver loads the row,
enforces the deletion guard (see :mod:`core.guards`) and deletes it, returning
the id. Sub-object permissions defer to a governing anchor — see
:func:`core.guards.resolve_anchor`.

Models that already ship a named delete mutation with its own input type
(Dataset, File, Trace, Block, ROI, Mechanism) keep those for backwards
compatibility; they call the same guard inline.
"""

import strawberry
import kante
from pydantic import BaseModel
from kante.types import Info

from core import models
from core.guards import enforce_delete


class DeleteInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteInputModel, description="Input for deleting an object by its id")
class DeleteInput:
    id: strawberry.ID = strawberry.field(description="The id of the object to delete")


def _delete(info: Info, model_cls: type, id: str) -> strawberry.ID:
    instance = model_cls.objects.get(id=id)
    enforce_delete(info, instance)
    instance.delete()
    return strawberry.ID(id)


def _make_delete(model_cls: type):
    """Build a guarded delete resolver for ``model_cls``."""

    def resolver(info: Info, input: DeleteInput) -> strawberry.ID:
        return _delete(info, model_cls, input.to_pydantic().id)

    resolver.__name__ = f"delete_{model_cls.__name__.lower()}"
    resolver.__qualname__ = resolver.__name__
    return resolver


delete_instrument = _make_delete(models.Instrument)
delete_model_collection = _make_delete(models.ModelCollection)
delete_mod_environment = _make_delete(models.ModEnvironment)
delete_neuron_model = _make_delete(models.NeuronModel)
delete_experiment = _make_delete(models.Experiment)
delete_experiment_recording_view = _make_delete(models.ExperimentRecordingView)
delete_experiment_stimulus_view = _make_delete(models.ExperimentStimulusView)
delete_block_group = _make_delete(models.BlockGroup)
delete_block_segment = _make_delete(models.BlockSegment)
delete_analog_signal = _make_delete(models.AnalogSignal)
delete_analog_signal_channel = _make_delete(models.AnalogSignalChannel)
delete_irregularly_sampled_signal = _make_delete(models.IrregularlySampledSignal)
delete_spike_train = _make_delete(models.SpikeTrain)
delete_simulation = _make_delete(models.Simulation)
delete_stimulus = _make_delete(models.Stimulus)
delete_recording = _make_delete(models.Recording)
delete_view_collection = _make_delete(models.ViewCollection)
delete_timeline_view = _make_delete(models.TimelineView)
