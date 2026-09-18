"""Filter tests for the folders query (FolderFilter).

Ported from mikro's ``tests/test_filters_folder.py``.
"""

import pytest
from asgiref.sync import sync_to_async

from tests.seed import create_folder

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

QUERY = """
    query List($filters: FolderFilter) {
        folders(filters: $filters) { id name }
    }
"""


async def names(aexecute, filters, context=None):  # noqa: ANN001, ANN201
    result = await aexecute(QUERY, {"filters": filters}, context=context)
    assert not result.errors, result.errors
    return {ds["name"] for ds in result.data["folders"]}


async def test_filter_by_parentless(aexecute, authenticated_context):
    root = await create_folder(authenticated_context, "Root")
    await create_folder(authenticated_context, "Child", parent=root)

    assert await names(aexecute, {"parentless": True}) == {"Root"}
    assert await names(aexecute, {"parentless": False}) == {"Child"}


async def test_filter_by_is_default(aexecute, authenticated_context):
    await create_folder(authenticated_context, "Default", is_default=True)
    await create_folder(authenticated_context, "Regular")

    assert await names(aexecute, {"isDefault": True}) == {"Default"}
    assert await names(aexecute, {"isDefault": False}) == {"Regular"}


async def test_filter_by_tags_and_pinned(aexecute, authenticated_context):
    tagged = await create_folder(authenticated_context, "Tagged")
    await create_folder(authenticated_context, "Plain")
    await sync_to_async(tagged.tags.add)("screening")
    await sync_to_async(tagged.pinned_by.add)(authenticated_context.request.user)

    assert await names(aexecute, {"tags": ["screening"]}) == {"Tagged"}
    assert await names(aexecute, {"pinned": True}) == {"Tagged"}
    assert await names(aexecute, {"pinned": False}) == {"Plain"}


async def test_pinned_is_per_user(aexecute, authenticated_context, bot_context):
    """A pin is the *caller's*: a folder someone else pinned is not pinned for you."""
    folder = await create_folder(authenticated_context, "Theirs to pin")
    await sync_to_async(folder.pinned_by.add)(bot_context.request.user)

    assert await names(aexecute, {"pinned": True}) == set()
    assert await names(aexecute, {"pinned": True}, context=bot_context) == {"Theirs to pin"}


async def test_filter_by_owner(aexecute, authenticated_context, bot_context):
    # The second user (sub 2) of the same organization: mikro's `create_other_user`.
    await create_folder(authenticated_context, "Mine")
    await create_folder(bot_context, "Theirs")

    # By the creator's *subject*, not their row id: "2" is the sub the static "bottest" token resolves to.
    assert bot_context.request.user.sub == "2"
    assert await names(aexecute, {"owner": "2"}) == {"Theirs"}
    assert await names(aexecute, {"owner": "1"}) == {"Mine"}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "core/filters.py::SearchFilterMixin.filter_search annotates `TrigramSimilarity`, i.e. Postgres' `similarity()`, which exists only once the `pg_trgm` extension is "
        "installed -- and nothing installs it: core/migrations/0001_initial.py has `CreateExtension('cube')` and no `TrigramExtension()`, and tests/conftest.py provisions `cube` only. "
        "So `folders(filters: {search: ...})` fails with `function similarity(character varying, unknown) does not exist`, as does `search` on every other filter built on "
        "that mixin (experiments, blocks, segments, signals, simulations, recordings, mechanisms, ...). A name collision in the port: mikro's FolderFilter inherits mikro's "
        "`SearchFilterMixin`, which is `name__search` (built-in full text, no extension); here the same base-class name resolves to this service's older trigram mixin. The ported "
        "filters on `NameSearchFilterMixin` (files, array datasets, coordinate systems) are unaffected. No test in the suite had ever passed `search` to a SearchFilterMixin filter."
    ),
)
async def test_filter_by_search(aexecute, authenticated_context):
    """The `search` half of mikro's `test_filter_by_search_and_description`."""
    await create_folder(authenticated_context, "Experiment", description="control slices")
    await create_folder(authenticated_context, "Other", description="treated slices")

    assert await names(aexecute, {"search": "Experiment"}) == {"Experiment"}


async def test_filter_by_description(aexecute, authenticated_context):
    """The `description` half of mikro's `test_filter_by_search_and_description`."""
    await create_folder(authenticated_context, "Experiment", description="control slices")
    await create_folder(authenticated_context, "Other", description="treated slices")

    assert await names(aexecute, {"description": {"iContains": "control"}}) == {"Experiment"}


async def test_filter_by_parent(aexecute, authenticated_context):
    """The parent filter lists the direct children of a folder."""
    root = await create_folder(authenticated_context, "Root")
    child = await create_folder(authenticated_context, "Child A", parent=root)
    await create_folder(authenticated_context, "Child B", parent=root)
    await create_folder(authenticated_context, "Grandchild", parent=child)
    await create_folder(authenticated_context, "Unrelated")

    assert await names(aexecute, {"parent": str(root.id)}) == {"Child A", "Child B"}


async def test_an_explicit_null_is_no_constraint(aexecute, authenticated_context):
    """`USE_DEPRECATED_FILTERS`: a resolver is handed the explicit `null` a client sent, and must read it as "not asked"."""
    root = await create_folder(authenticated_context, "Root")
    await create_folder(authenticated_context, "Child", parent=root)

    nothing_asked = {"parentless": None, "parent": None, "pinned": None, "tags": None, "owner": None, "search": None, "createdBefore": None, "createdAfter": None}
    for field in nothing_asked:
        assert await names(aexecute, {field: None}) == {"Root", "Child"}, field
    assert await names(aexecute, nothing_asked) == {"Root", "Child"}


@pytest.mark.parametrize("field", ["isDefault", "id"])
@pytest.mark.xfail(
    strict=True,
    reason=(
        "core/filters.py::FolderFilter declares `is_default: Optional[bool]` and `id: auto` as plain fields, not `@kante.filter_field` resolvers. Under "
        "`USE_DEPRECATED_FILTERS: True` strawberry-django turns an explicit null on a plain field into `<column> IS NULL`, which no folder satisfies, so "
        "`folders(filters: {isDefault: null})` -- what a client sends for an unset nullable variable -- returns nothing. Every resolver-backed filter beside it guards "
        "with `if value is None: return Q()`; these two have no resolver to put the guard in."
    ),
)
async def test_an_explicit_null_on_a_plain_field_is_no_constraint(aexecute, authenticated_context, field: str):
    root = await create_folder(authenticated_context, "Root")
    await create_folder(authenticated_context, "Child", parent=root)

    assert await names(aexecute, {field: None}) == {"Root", "Child"}


async def test_folders_are_listed_per_organization(aexecute, authenticated_context, other_org_context):
    """Every list here is organization-scoped, whatever the filter says."""
    mine = await create_folder(authenticated_context, "Mine")
    await create_folder(authenticated_context, "Mine too", parent=mine)
    await create_folder(other_org_context, "Theirs")

    assert await names(aexecute, {}) == {"Mine", "Mine too"}
    assert await names(aexecute, {}, context=other_org_context) == {"Theirs"}
    assert await names(aexecute, {"parent": str(mine.id)}, context=other_org_context) == set(), "naming another organization's folder lists nothing under it"
