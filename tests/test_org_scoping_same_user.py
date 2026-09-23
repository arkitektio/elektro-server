"""Cross-organization scoping for ONE user who belongs to two organizations.

``test_tenancy`` / ``test_scoping`` pin the boundary with a different user in the other org.
That misses the case where the boundary actually gets crossed in practice: the same person,
switching the org they act in. Everything created while acting in ``static_org`` (token
"test") must be invisible, and unreferenceable, while acting in ``other_org`` (token
"test-other-org").
"""

import pytest
from graphql import GraphQLInterfaceType, GraphQLList, GraphQLNonNull, GraphQLObjectType, Undefined
from kante.context import HttpContext

from core.models import Folder
from elektro_server.schema import schema
from tests.seed import create_array_dataset, create_file, create_folder, create_lens, create_table_dataset


def _unwrap(graphql_type):
    while isinstance(graphql_type, (GraphQLNonNull, GraphQLList)):
        graphql_type = graphql_type.of_type
    return graphql_type


def _root_list_fields() -> list[str]:
    """Every Query field that lists rows with an `id` and needs no argument -- found, not listed."""
    names = []
    for name, field in schema._schema.query_type.fields.items():
        inner = field.type.of_type if isinstance(field.type, GraphQLNonNull) else field.type
        if not isinstance(inner, GraphQLList):
            continue
        target = _unwrap(inner)
        if not isinstance(target, (GraphQLObjectType, GraphQLInterfaceType)) or "id" not in target.fields:
            continue
        if any(isinstance(arg.type, GraphQLNonNull) and arg.default_value is Undefined for arg in field.args.values()):
            continue
        names.append(name)
    return names


async def _seed(ctx: HttpContext) -> None:
    folder = await create_folder(ctx, "Home")
    await folder.pinned_by.aadd(ctx.request.user)
    await create_file(ctx, "raw.nwb", folder)
    dataset = await create_array_dataset(ctx, "Trace")
    await create_lens(ctx, dataset)
    await create_table_dataset(ctx, "Events")


async def _ids(field: str, ctx: HttpContext, args: str = "") -> list[str]:
    result = await schema.execute(f"query {{ {field}{args} {{ id }} }}", context_value=ctx)
    assert not result.errors, (field, result.errors)
    return [row["id"] for row in result.data[field]]


def test_the_field_discovery_finds_the_folder_lists() -> None:
    fields = _root_list_fields()
    assert {"folders", "myfolders", "files", "myfiles", "arrayDatasets"} <= set(fields)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_fields_hide_the_other_org(db, authenticated_context: HttpContext, same_user_other_org_context: HttpContext):
    await _seed(authenticated_context)

    # Sanity: the seeding org sees its own rows, so an empty list below means scoped, not broken.
    assert await _ids("folders", authenticated_context)
    assert await _ids("arrayDatasets", authenticated_context)

    leaks = {field: ids for field in _root_list_fields() if (ids := await _ids(field, same_user_other_org_context))}
    assert not leaks, f"the same user acting in another org sees: {leaks}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_pinned_and_mine_stay_in_the_acting_org(db, authenticated_context: HttpContext, same_user_other_org_context: HttpContext):
    await _seed(authenticated_context)

    assert await _ids("folders", authenticated_context, "(filters: {pinned: true})")
    assert not await _ids("folders", same_user_other_org_context, "(filters: {pinned: true})")
    assert await _ids("myfolders", authenticated_context)
    assert not await _ids("myfolders", same_user_other_org_context)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_my_fields_only_list_the_callers_rows(db, authenticated_context: HttpContext, bot_context: HttpContext):
    mine = await create_folder(authenticated_context, "Mine")
    theirs = await create_folder(bot_context, "Theirs")
    my_file = await create_file(authenticated_context, "mine.nwb", mine)
    their_file = await create_file(bot_context, "theirs.nwb", theirs)

    folder_ids = await _ids("myfolders", authenticated_context)
    assert str(mine.pk) in folder_ids and str(theirs.pk) not in folder_ids
    file_ids = await _ids("myfiles", authenticated_context)
    assert str(my_file.pk) in file_ids and str(their_file.pk) not in file_ids


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["createFolder", "ensureFolder", "updateFolder"])
async def test_folder_parent_must_be_in_the_acting_org(db, mutation: str, authenticated_context: HttpContext, same_user_other_org_context: HttpContext):
    parent = await create_folder(authenticated_context, "Org A Parent")
    own = await create_folder(same_user_other_org_context, "Org B Folder")
    extra = f', id: "{own.pk}"' if mutation == "updateFolder" else ""

    result = await schema.execute(
        f"""
        mutation($parent: ID!) {{
            {mutation}(input: {{name: "Smuggled", parent: $parent{extra}}}) {{ id }}
        }}
        """,
        variable_values={"parent": str(parent.pk)},
        context_value=same_user_other_org_context,
    )
    assert result.errors, f"{mutation} nested a folder under another org's folder"
    assert not await Folder.objects.filter(name="Smuggled").aexists()
    assert not await Folder.objects.filter(parent=parent).aexists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rename_without_parent_keeps_the_parent(db, authenticated_context: HttpContext):
    parent = await create_folder(authenticated_context, "Parent")
    child = await create_folder(authenticated_context, "Child", parent=parent)

    result = await schema.execute(
        'mutation($id: ID!) { updateFolder(input: {id: $id, name: "Renamed"}) { id } }',
        variable_values={"id": str(child.pk)},
        context_value=authenticated_context,
    )
    assert not result.errors, result.errors
    await child.arefresh_from_db()
    assert child.name == "Renamed"
    assert child.parent_id == parent.pk


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_children_do_not_cross_orgs(db, authenticated_context: HttpContext, same_user_other_org_context: HttpContext):
    """Even a cross-org row already in the database (written before the fix) stays out of `children`."""
    parent = await create_folder(authenticated_context, "Org A Parent")
    await create_folder(same_user_other_org_context, "Org B Child", parent=parent)

    result = await schema.execute(
        'query($parent: ID!) { children(parent: $parent) { ... on Folder { id name } } }',
        variable_values={"parent": str(parent.pk)},
        context_value=authenticated_context,
    )
    assert not result.errors, result.errors
    assert result.data["children"] == []
