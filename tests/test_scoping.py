"""Organization-scoping infrastructure (core.scoping).

These pin the cross-cutting tenant-scoping seam that the datalayer (and, over
time, the rest of core) funnels single-row reads through. End-to-end mutation
enforcement is wired model-by-model as a separate effort; here we exercise the
helpers directly so the pattern is covered as soon as it lands.
"""

from types import SimpleNamespace

import pytest
from kante.context import HttpContext

from core import scoping
from core.models import ArrayDataset, Folder


def _fake_info(organization):
    """A minimal stand-in for kante's Info — for_org only reads request.organization."""
    return SimpleNamespace(context=SimpleNamespace(request=SimpleNamespace(organization=organization)))


def test_organization_path_direct():
    # Both models carry a direct organization FK, so the lookup path is trivial.
    assert scoping.organization_path(Folder) == "organization"
    assert scoping.organization_path(ArrayDataset) == "organization"


@pytest.mark.django_db(transaction=True)
def test_for_org_scopes_queryset(authenticated_context: HttpContext, other_org_context: HttpContext):
    org_a = authenticated_context.request.organization
    org_b = other_org_context.request.organization

    ds_a = Folder.objects.create(
        name="Org A Folder",
        creator=authenticated_context.request.user,
        organization=org_a,
        membership=authenticated_context.request.membership,
    )
    ds_b = Folder.objects.create(
        name="Org B Folder",
        creator=other_org_context.request.user,
        organization=org_b,
        membership=other_org_context.request.membership,
    )

    scoped_a = scoping.for_org(Folder, _fake_info(org_a))  # type: ignore[arg-type]
    assert list(scoped_a.values_list("pk", flat=True)) == [ds_a.pk]

    scoped_b = scoping.for_org(Folder, _fake_info(org_b))  # type: ignore[arg-type]
    assert list(scoped_b.values_list("pk", flat=True)) == [ds_b.pk]


# --- every model is scoped, and the path to its organization is pinned ----------------------
#
# `_find_org_path` follows the first required FK it finds, in field order. That works, and it
# is an accident waiting for a reordered field: so the path of every model is written down
# here, and a new model has to be added on purpose.

ORGANIZATION_PATHS = {
    "Annotation": "collection__organization",
    "AnnotationCollection": "organization",
    "AcquisitionMetadata": "anchor__organization",
    "ArrayDataset": "organization",
    "Axis": "coordinate_system__organization",
    "ChannelLabel": "anchor__organization",
    "CoordinateAnchor": "organization",
    "Column": "table__organization",
    "CoordinateSystem": "organization",
    "DataArray": "dataset__organization",
    "Experiment": "organization",
    "ExperimentLayer": "experiment__organization",
    "File": "organization",
    "FileLink": "organization",
    "Folder": "organization",
    "Lens": "dataset__organization",
    "Mechanism": "environment__organization",
    "ModEnvironment": "organization",
    "ModelCollection": "organization",
    "ModelWorkspace": "organization",
    "NeuronModel": "environment__organization",
    "RecordingSite": "anchor__organization",
    "RigState": "anchor__organization",
    "SimulationState": "anchor__organization",
    "SparseArray": "dataset__organization",
    "SparseAxisReference": "dataset__organization",
    "SparseDataset": "organization",
    "StimulusSite": "anchor__organization",
    "TableDataset": "organization",
    "Transformation": "organization",
    "ValueHistogram": "anchor__organization",
    "ValueUnit": "anchor__organization",
    "WorkspaceMapping": "workspace__organization",
}


def _core_models():
    from django.apps import apps

    return [model for model in apps.get_app_config("core").get_models() if not model.__name__.startswith("Historical")]


def test_every_model_is_listed():
    assert sorted(model.__name__ for model in _core_models()) == sorted(ORGANIZATION_PATHS), "a new model must state how it reaches its organization"


@pytest.mark.parametrize("model", _core_models(), ids=lambda model: model.__name__)
def test_every_model_reaches_an_organization_over_required_links(model):
    scoping.organization_path.cache_clear()
    path = scoping.organization_path(model)
    assert path == ORGANIZATION_PATHS[model.__name__]

    # A nullable link on the way would silently hide every row whose link is null from scoped reads.
    current = model
    for name in path.split("__"):
        field = current._meta.get_field(name)
        assert not field.null, f"{current.__name__}.{name} is nullable, so rows without it would vanish from every scoped read"
        current = field.related_model


# --- the one relaxation: a relation of an already-scoped parent keeps its prefetch ---------------


@pytest.mark.django_db(transaction=True)
def test_nested_scoping_relaxes_only_for_the_relation_of_a_known_parent(authenticated_context: HttpContext, other_org_context: HttpContext):
    """`OrgScopedOrNested` must scope every root read, and leave alone only what is visibly a parent's relation.

    It exists because re-filtering a prefetched relation throws the prefetch away (a query per
    coordinate system in `coordinateGraph`). The two marks it trusts are ones a client cannot
    cause: a root queryset is never bound to an instance and is never already evaluated.
    """
    from core.models import Axis, CoordinateSystem
    from core.types._shared import OrgScopedOrNested

    mine = CoordinateSystem.objects.create(name="mine", organization=authenticated_context.request.organization)
    theirs = CoordinateSystem.objects.create(name="theirs", organization=other_org_context.request.organization)
    Axis.objects.create(coordinate_system=mine, order=0, name="t", type="TIME")
    Axis.objects.create(coordinate_system=theirs, order=0, name="t", type="TIME")

    info = SimpleNamespace(variable_values={}, context=SimpleNamespace(request=SimpleNamespace(organization=authenticated_context.request.organization)))

    # A root list: scoped, whatever else is true of it.
    root = OrgScopedOrNested.get_queryset(Axis.objects.all(), info)
    assert [axis.coordinate_system_id for axis in root] == [mine.pk]
    assert [axis.coordinate_system_id for axis in OrgScopedOrNested.get_queryset(Axis.objects.filter(name="t").order_by("id"), info)] == [mine.pk]

    # The relation of a parent the request already holds: returned as it came, prefetch intact.
    parent = CoordinateSystem.objects.prefetch_related("axes").get(pk=mine.pk)
    nested = parent.axes.all()
    assert OrgScopedOrNested.get_queryset(nested, info) is nested
