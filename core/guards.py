"""Authorization guards for destructive mutations.

A single predicate, :func:`can_delete`, decides whether the current user may
delete an object. Models that don't carry ownership themselves (sub-objects
like a ``Recording`` or an ``AnalogSignal``) defer the decision to their
*governing anchor* — the parent that does carry a creator/provenance (e.g. the
``Simulation`` a recording belongs to, or the ``Block`` a segment belongs to).

The rule, evaluated against the anchor:

1. Members holding the ``admin`` role in the active organization may delete
   anything.
2. The user who originally *assigned the task* that created the object may
   delete it (resolved from the earliest provenance history row).
3. The ``creator`` may delete it — unless the creator is a ``bot``, in which
   case ownership belongs to the task assigner (rule 2), not the bot account.
"""

from __future__ import annotations

from typing import Any

from kante.types import Info

from core import models

ADMIN_ROLE = "admin"
BOT_ROLE = "bot"


# Attribute chain from a model to its governing anchor. An empty tuple means
# the model is its own anchor (it carries creator/provenance directly).
ANCHOR_PATHS: dict[type, tuple[str, ...]] = {
    # Self-anchored: carry creator and/or provenance directly.
    models.Dataset: (),
    models.Instrument: (),
    models.File: (),
    models.ModelCollection: (),
    models.ModEnvironment: (),
    models.NeuronModel: (),
    models.Experiment: (),
    models.Block: (),
    models.Trace: (),
    models.Simulation: (),
    models.ViewCollection: (),
    models.ROI: (),
    # Governed by a parent anchor.
    models.Mechanism: ("environment",),
    models.ExperimentRecordingView: ("experiment",),
    models.ExperimentStimulusView: ("experiment",),
    models.BlockGroup: ("session",),
    models.BlockSegment: ("session",),
    models.AnalogSignal: ("recording_segment", "session"),
    models.AnalogSignalChannel: ("signal", "recording_segment", "session"),
    models.IrregularlySampledSignal: ("recording_segment", "session"),
    models.SpikeTrain: ("recording_segment", "session"),
    models.Stimulus: ("simulation",),
    models.Recording: ("simulation",),
    models.TimelineView: ("trace",),
}


class PermissionDenied(Exception):
    """Raised when the current user may not perform the requested action."""


def resolve_anchor(instance: Any) -> Any:
    """Walk to the object that governs permissions for ``instance``.

    Follows the configured attribute chain. If a nullable link in the chain is
    missing, the deepest object reached is returned — that object typically has
    no creator, so the guard falls back to admin-only, which is the safe choice.
    """
    path = ANCHOR_PATHS.get(type(instance), ())
    anchor = instance
    for attr in path:
        nxt = getattr(anchor, attr, None)
        if nxt is None:
            break
        anchor = nxt
    return anchor


def _current_roles(request: Any) -> list[str]:
    """Roles the current user holds in the active organization."""
    try:
        membership = request.membership
    except ValueError:
        return []
    return membership.roles or []


def _original_task_assigner(anchor: Any) -> Any | None:
    """The user who assigned the task that created ``anchor`` (if any).

    Resolved from the earliest provenance history row. Objects created outside
    a Rekuest task (plain API calls) have no task and yield ``None``.
    """
    manager = getattr(anchor, "provenance_entries", None)
    if manager is None:
        return None
    creation = manager.filter(history_type="+").order_by("history_date").first()
    if creation is None:
        creation = manager.order_by("history_date").first()
    task = getattr(creation, "task", None) if creation is not None else None
    return getattr(task, "assigner", None) if task is not None else None


def can_delete(info: Info, instance: Any) -> bool:
    """Whether the current user may delete ``instance`` (or its anchor)."""
    request = info.context.request
    user = request.user
    roles = _current_roles(request)

    # 1. Organization admins may delete anything.
    if ADMIN_ROLE in roles:
        return True

    anchor = resolve_anchor(instance)

    # 2. The user who originally assigned the creating task.
    assigner = _original_task_assigner(anchor)
    if assigner is not None and assigner.id == user.id:
        return True

    # 3. The creator — unless the creator is a bot, in which case ownership
    #    sits with the task assigner (rule 2), not the bot account. The creator
    #    here is the current user, so their active-org roles decide bot status.
    creator = getattr(anchor, "creator", None)
    if creator is not None and creator.id == user.id and BOT_ROLE not in roles:
        return True

    return False


def enforce_delete(info: Info, instance: Any) -> None:
    """Raise :class:`PermissionDenied` unless the current user may delete ``instance``."""
    if not can_delete(info, instance):
        raise PermissionDenied(
            f"You are not allowed to delete this {type(instance).__name__}."
        )
