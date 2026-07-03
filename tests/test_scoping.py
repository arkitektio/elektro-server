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
from core.models import Dataset, Trace


def _fake_info(organization):
    """A minimal stand-in for kante's Info — for_org only reads request.organization."""
    return SimpleNamespace(context=SimpleNamespace(request=SimpleNamespace(organization=organization)))


def test_organization_path_direct():
    # Both models carry a direct organization FK, so the lookup path is trivial.
    assert scoping.organization_path(Dataset) == "organization"
    assert scoping.organization_path(Trace) == "organization"


@pytest.mark.django_db(transaction=True)
def test_for_org_scopes_queryset(authenticated_context: HttpContext, other_org_context: HttpContext):
    org_a = authenticated_context.request.organization
    org_b = other_org_context.request.organization

    ds_a = Dataset.objects.create(
        name="Org A Dataset",
        creator=authenticated_context.request.user,
        organization=org_a,
        membership=authenticated_context.request.membership,
    )
    ds_b = Dataset.objects.create(
        name="Org B Dataset",
        creator=other_org_context.request.user,
        organization=org_b,
        membership=other_org_context.request.membership,
    )

    scoped_a = scoping.for_org(Dataset, _fake_info(org_a))  # type: ignore[arg-type]
    assert list(scoped_a.values_list("pk", flat=True)) == [ds_a.pk]

    scoped_b = scoping.for_org(Dataset, _fake_info(org_b))  # type: ignore[arg-type]
    assert list(scoped_b.values_list("pk", flat=True)) == [ds_b.pk]
