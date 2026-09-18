"""Guarded delete mutations.

A single shared ``DeleteInput`` (an id) feeds a family of resolvers, one per
model that didn't already have a bespoke delete. Each resolver loads the row,
enforces the deletion guard (see :mod:`core.guards`) and deletes it, returning
the id. Sub-object permissions defer to a governing anchor — see
:func:`core.guards.resolve_anchor`.

Models that already ship a named delete mutation with its own input type
(Folder, File, ArrayDataset, TableDataset, SparseDataset, Annotation, Mechanism) keep those; they go through the
same guard and the same store straddle (:mod:`core.mutations._generic`).
"""

import strawberry
import kante
from pydantic import BaseModel
from kante.types import Info

from core import models
from core.guards import enforce_delete
from core.scoping import get_for_org


class DeleteInputModel(BaseModel):
    id: str


@kante.pydantic_input(DeleteInputModel, description="Input for deleting an object by its id")
class DeleteInput:
    id: strawberry.ID = strawberry.field(description="The id of the object to delete")


def delete_flagging_stores(instance) -> None:  # noqa: ANN001 - any model row
    """Delete a row, and flag the stores that delete leaves with nobody pointing at them.

    mikro's ``make_delete`` straddle, as one function every delete resolver here goes through.
    A store is never deleted *with* its data row: the bytes may be large, the delete may be a
    mistake, and S3 has no undo. The rows this delete will take are collected first (they are
    gone afterwards, and with them the answer), then each store they leave unreferenced gets
    ``orphaned_at`` stamped. ``purge_orphaned_stores`` collects those after a grace period, and
    re-checks for referrers before it removes anything.
    """
    from django.db import transaction

    from core.logic import storage

    with transaction.atomic():
        orphaned = storage.stores_orphaned_by(instance)
        instance.delete()
        storage.flag_orphaned(orphaned)


def _delete(info: Info, model_cls: type, id: str) -> strawberry.ID:
    instance = get_for_org(model_cls, info, id=id)
    enforce_delete(info, instance)
    delete_flagging_stores(instance)
    return strawberry.ID(id)


def _make_delete(model_cls: type):
    """Build a guarded delete resolver for ``model_cls``."""

    def resolver(info: Info, input: DeleteInput) -> strawberry.ID:
        return _delete(info, model_cls, input.to_pydantic().id)

    resolver.__name__ = f"delete_{model_cls.__name__.lower()}"
    resolver.__qualname__ = resolver.__name__
    return resolver


delete_model_collection = _make_delete(models.ModelCollection)
delete_model_workspace = _make_delete(models.ModelWorkspace)
delete_workspace_mapping = _make_delete(models.WorkspaceMapping)
delete_mod_environment = _make_delete(models.ModEnvironment)
delete_neuron_model = _make_delete(models.NeuronModel)
delete_experiment = _make_delete(models.Experiment)
delete_layer = _make_delete(models.ExperimentLayer)
