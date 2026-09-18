"""Factories for the delete and pin mutations that every entity repeats.

The counterpart of mikro's ``core/mutations/_generic.py``, kept at the same path so the
mutation modules vendored from it import the same names. What differs is *who may delete*:
mikro passes an ``owner`` callable per model, this service has one predicate for all of them
(:func:`core.guards.enforce_delete`, keyed by :data:`core.guards.ANCHOR_PATHS`), so there is
no ``owner`` argument here. What is the same is the store straddle -- see
:func:`core.mutations.delete.delete_flagging_stores`.
"""

from kante.types import Info
import strawberry

from core import scoping
from core.guards import enforce_delete
from core.mutations.delete import delete_flagging_stores


def make_delete(model, input_type, guard=None):  # noqa: ANN001, ANN201 - a resolver factory
    """Build a delete resolver: fetch org-scoped by id, guard, delete, flag orphaned stores.

    ``guard`` is a callable raising when the row must not be deleted *at all*, whoever asks
    -- the PROTECT half, where :func:`enforce_delete` is the permission half. It runs after
    the permission check, so a caller who may not delete the row hears that first rather
    than learning what else references it.
    """

    def resolve(info: Info, input: input_type) -> strawberry.ID:
        parsed = input.to_pydantic()
        item = scoping.get_for_org(model, info, id=parsed.id)
        enforce_delete(info, item)
        if guard is not None:
            guard(item)
        delete_flagging_stores(item)
        return parsed.id

    resolve.__name__ = f"delete_{model.__name__.lower()}"
    return resolve



def make_owned_space_delete(model, input_type, guard=None):  # noqa: ANN001, ANN201 - a resolver factory
    """:func:`make_delete` for a container that owns its space, which it sweeps after itself.

    elektro's own (divergence 7 in ``core/DESIGN.md``). A table or sparse dataset owns its
    coordinate system, but its FK to it is PROTECT, so deleting the data cannot cascade into
    the space -- mikro leaves such a space to an orphan sweep. Here the delete sweeps it in the
    same request, exactly as ``deleteArrayDataset`` sweeps a sample grid: the space goes only
    if nothing else lives in it and nothing is laid out over it, and every edge touching it --
    a sampling law, a derivation, a key edge -- goes with it.
    """
    from core.logic import spaces as spaces_logic

    def resolve(info: Info, input: input_type) -> strawberry.ID:
        parsed = input.to_pydantic()
        item = scoping.get_for_org(model, info, id=parsed.id)
        enforce_delete(info, item)
        if guard is not None:
            guard(item)
        systems = {item.coordinate_system_id}
        delete_flagging_stores(item)
        spaces_logic.sweep_empty_systems(systems)
        return parsed.id

    resolve.__name__ = f"delete_{model.__name__.lower()}"
    return resolve

def make_pin(model, input_type, return_type):  # noqa: ANN001, ANN201 - a resolver factory
    """Build a pin resolver toggling the request user on the pinned_by M2M."""

    def resolve(info: Info, input: input_type) -> return_type:
        parsed = input.to_pydantic()
        item = scoping.get_for_org(model, info, id=parsed.id)
        if parsed.pin:
            item.pinned_by.add(info.context.request.user)
        else:
            item.pinned_by.remove(info.context.request.user)
        return item

    resolve.__name__ = f"pin_{model.__name__.lower()}"
    return resolve
