"""What every type module needs and none of them may own: tenant scoping of reads.

Lives here, not in ``core/types/__init__.py``, so that a type module split out of it
(``core/types/coords.py``) can import the mixin without importing the package that imports it.
"""

from core import scoping


def build_prescoped_queryset(info, queryset):
    """Scope a list queryset to the request's organization.

    Honors an explicit ``filters.scope`` override (not yet implemented) and
    otherwise filters by the model's discovered organization path (see
    :mod:`core.scoping`). Mirrors the single-object scoping in ``core.scoping``
    so list fields and by-id lookups stay tenant-consistent.
    """
    if (info.variable_values.get("filters") or {}).get("scope") is not None:
        raise Exception("Custom scopes not implemented yet")

    path = scoping.organization_path(queryset.model)
    if path is None:
        if queryset.model.__name__ not in scoping.UNSCOPED_MODELS:
            raise LookupError(f"{queryset.model.__name__} has no path to an organization and is not registered in core.scoping.UNSCOPED_MODELS")
        return queryset
    return queryset.filter(**{path: info.context.request.organization})


def build_prescoper():
    def prescoper(queryset, info):
        return build_prescoped_queryset(info, queryset)

    return prescoper


class OrgScoped:
    """Mixin that scopes a type's list/relation queryset to the request org.

    strawberry_django calls ``get_queryset`` for both top-level list fields and
    nested relation resolution, so mixing this in tenant-scopes every read of the
    type. Resolved via MRO, so it is enough to list it as a base class.
    """

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):
        return build_prescoped_queryset(info, queryset)


class OrgScopedOrNested(OrgScoped):
    """Tenant scoping for a type that is *also* read as a relation of an already-scoped row.

    strawberry_django calls ``get_queryset`` for nested relations as well as for root lists,
    and a filter on a related manager's queryset throws its prefetch away: the rows are
    fetched again, once per parent. For an axis of a coordinate system, or the children of a
    wrapper transformation, that turned ``coordinateGraph`` -- which prefetches both, because
    a custom resolver's plain list is invisible to the optimizer -- into a query per system.

    Such a row carries no tenancy question of its own *when nested*: it is reached through a
    parent the request already read scoped, and it cannot belong to another organization than
    that parent (an axis is created with its system, a child with its wrapper). So a queryset
    that is visibly "the relation of a known parent" is returned as it came:

    * ``_result_cache`` filled -- the prefetch already ran;
    * ``_known_related_objects`` set -- Django's mark of a reverse manager bound to one instance.

    Anything else -- a root list, a by-id lookup -- is scoped exactly as :class:`OrgScoped` does.
    Used only where both conditions above hold by construction; it is not a general relaxation.
    """

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):
        if getattr(queryset, "_result_cache", None) is not None or getattr(queryset, "_known_related_objects", None):
            return queryset
        return build_prescoped_queryset(info, queryset)


def apply_link_filters(queryset, filters_input, info) -> list:  # noqa: ANN001 - a QuerySet, a strawberry filter input, kante's Info
    """Apply an optional ``FileLinkFilter`` to a link queryset and evaluate it.

    Vendored from mikro. Lives here because several resolvers across modules need it --
    ``sourceFiles`` and ``exports`` on each container, plus ``derivedContainers`` and
    ``exportedFrom`` on ``File``.

    It is also the seam that publishes ``FileLinkFilter`` into the SDL at all. Declaring the
    filter on the django_type is not enough: nothing referenced it, so it was silently absent
    from the schema. A filter type reaches the SDL only by being some field's argument.
    """
    import strawberry
    import strawberry_django

    if filters_input is not strawberry.UNSET and filters_input is not None:
        queryset = strawberry_django.filters.apply(filters_input, queryset, info)
    return list(queryset)
