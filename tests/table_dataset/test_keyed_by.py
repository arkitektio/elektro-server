"""`keyedBy`: authoring the FIELD dereference in the same call that creates the table.

**Ported from mikro** (``mikro/tests/test_keyed_by.py``). mikro reads the edges back through
``attributePlans`` and keys tables by mesh collections too; neither exists here, so the tests
that needed them were dropped and the plan assertions read the FIELD edge itself. In elektro a
mask keying a table is, e.g., a per-sample unit-assignment array keying a unit table.

A table of per-object measurements stands in two relations to the mask its rows were
measured out of, and they run in opposite directions:

* ``derivedFrom`` -- table -> mask, the lineage. UNMAPPABLE, because a row is an object and
  an object is not anywhere, so nothing places the table.
* ``keyedBy`` -- mask -> table, the dereference. A FIELD, and the only direction
  ``attributePlans`` can discover, because it looks for FIELD edges *landing on* a table.

Both are true, so both are written, and the point of ``keyedBy`` is that one mutation says
both instead of a create followed by a ``createTransformation`` that can fail after the
table is already stored.

The load-bearing test is :func:`test_keyed_by_derives_the_axis_split_from_the_two_spaces`:
the caller states no axes at all. The rank rule says the axes a FIELD does not consume pass
through by name, which leaves exactly one split for a given pair of systems -- so asking a
client for it would only be an opportunity to get it wrong, and a FIELD whose axes are
wrong is not refused at read, it is silently skipped.
"""

import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import enums, models
from elektro_server.schema import schema
from tests import seed

CREATE_TABLE = """
mutation Create($input: CreateTableDatasetInput!) {
  createTableDataset(input: $input) {
    id
    name
    columns { name role references { id name } }
    coordinateSystem { id axes { name type } }
    derivedFrom { id kind input { id } output { id } }
  }
}
"""


#: A timelapse mask: per-frame object ids, so the table key is (t, i) and t passes through.
TYX_AXES = [
    seed.axis("t", enums.AxisType.TIME),
    seed.axis("y", enums.AxisType.SPACE),
    seed.axis("x", enums.AxisType.SPACE),
]

#: The columns of a per-object table keyed by (t, i). Declared time-then-custom-then-space,
#: which is the axis type ordering the table's space inherits.
OBJECT_COLUMNS = [
    {"name": "t", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "TIME"},
    {"name": "i", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
    {"name": "area", "dtype": "DOUBLE", "role": "ATTRIBUTE"},
]


async def _mask(ctx: HttpContext, name: str = "nuclei labels", axes: list | None = None, shapes: list | None = None) -> models.ArrayDataset:
    """A label-mask dataset whose level-0 array has a zarr store a plan can name."""
    dataset = await seed.create_array_dataset(ctx, name, axes=axes or TYX_AXES, shapes=shapes or [[10, 64, 64]])

    def attach() -> None:
        store = models.ZarrStore.objects.create(path=f"s3://zarr/{name}", bucket="zarr", key=name.replace(" ", "-"), organization=ctx.request.organization)
        array = dataset.data_arrays.get(level=0)
        array.store = store
        array.save()

    await sync_to_async(attach)()
    return dataset


async def _create(ctx: HttpContext, name: str, columns: list[dict], **extra: object) -> object:
    return await schema.execute(
        CREATE_TABLE,
        context_value=ctx,
        variable_values={"input": await seed.table_input(ctx, name, columns, **extra)},
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_table_with_no_axes_cannot_be_keyed_at_all(authenticated_context: HttpContext):
    """It used to be a runtime refusal. It is now inexpressible, which is the better guarantee.

    A table with no `axes` has the synthetic `object` axis, which has no column behind it, so
    an id could never be looked up in it -- the edge wrote fine and `attributePlans` silently
    returned nothing, which is the failure the old check turned into a sentence. Identification
    travels *on an axis* now, and this table has none, so there is nowhere to put one. The
    only way to key it is to give it an axis, which is exactly the fix the old message asked
    for -- so the refusal has become the shape of the input.
    """
    mask = await _mask(authenticated_context)

    result = await _create(
        authenticated_context,
        "measurements",
        [{"name": "area", "dtype": "DOUBLE", "role": "ATTRIBUTE"}],
    )
    assert not result.errors, result.errors
    table = result.data["createTableDataset"]
    assert [axis["name"] for axis in table["coordinateSystem"]["axes"]] == ["object"], "the synthetic axis"

    # And the input has no field that could name a source for it: `identifiedBy` lives on the
    # declared `ColumnInput`s, and the synthetic axis corresponds to no declared column.
    assert "keyedBy" not in str(schema.as_str().split("input CreateTableDatasetInput")[1][:400])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_keyed_by_refuses_a_mask_that_consumes_nothing(authenticated_context: HttpContext):
    """A mask whose every axis is also a table axis collapses nothing, so it is not a map."""
    mask = await _mask(authenticated_context)

    result = await _create(
        authenticated_context,
        "localizations",
        [
            {"name": "t", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "TIME"},
            {"name": "i", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
            {"name": "y", "dtype": "DOUBLE", "role": "COORDINATE", "axisType": "SPACE"},
            {"name": "x", "dtype": "DOUBLE", "role": "COORDINATE", "axisType": "SPACE"},
        ],
        keyed_by=[{"kind": "DATASET", "dataset": str(mask.pk)}],
    )
    assert result.errors
    assert "consume nothing" in str(result.errors[0])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_keyed_by_refuses_a_table_that_produces_nothing(authenticated_context: HttpContext):
    """A table with no coordinate of its own has nothing for the pixels to supply.

    The refusal is now the *specific* one, because the caller names the axis: `t` is an axis of
    the mask too, so it passes through rather than being supplied. "The edge would produce
    nothing" was what that looked like from the derivation's side, and said nothing about which
    axis was meant -- it is now unreachable through either create, both of which state
    `produces`.
    """
    mask = await _mask(authenticated_context)

    result = await _create(
        authenticated_context,
        "per frame",
        [
            {"name": "t", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "TIME"},
            {"name": "count", "dtype": "BIGINT", "role": "ATTRIBUTE"},
        ],
        identified_by={"t": [{"kind": "DATASET", "dataset": str(mask.pk)}]},
    )
    assert result.errors
    message = str(result.errors[0])
    assert "was declared to key 't'" in message
    assert "passes through rather than being supplied" in message


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_keyed_by_refuses_the_same_mask_twice(authenticated_context: HttpContext):
    """A second edge between the same pair says nothing the first did not."""
    mask = await _mask(authenticated_context)

    result = await _create(
        authenticated_context,
        "nuclei morphology",
        OBJECT_COLUMNS,
        keyed_by=[{"kind": "DATASET", "dataset": str(mask.pk)}, {"kind": "DATASET", "dataset": str(mask.pk)}],
    )
    assert result.errors
    assert "distinct source" in str(result.errors[0])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_refused_key_edge_leaves_no_table_behind(authenticated_context: HttpContext):
    """The whole creation is one transaction, so a bad mask does not strand a table."""
    mask = await _mask(authenticated_context)

    result = await _create(
        authenticated_context,
        "per frame",
        [
            {"name": "t", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "TIME"},
            {"name": "count", "dtype": "BIGINT", "role": "ATTRIBUTE"},
        ],
        identified_by={"t": [{"kind": "DATASET", "dataset": str(mask.pk)}]},
    )
    assert result.errors
    assert not await sync_to_async(models.TableDataset.objects.filter(name="per frame").exists)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_keying_a_table_does_not_make_the_mask_derived_from_it(authenticated_context: HttpContext):
    """The FIELD leaves the mask's system and lands in a table's, which is the shape
    ``derivedFrom`` reports for a dataset -- so check it is not read as lineage.

    A mask is not computed *from* the table it keys; the arrow only happens to point that
    way because a dereference runs from pixels to records.
    """
    mask = await _mask(authenticated_context)
    mask_system = await sync_to_async(lambda: mask.intrinsic_coordinate_system)()

    result = await _create(authenticated_context, "nuclei morphology", OBJECT_COLUMNS, identified_by={"i": [{"kind": "DATASET", "dataset": str(mask.pk)}]})
    assert not result.errors, result.errors

    mask_lineage = await schema.execute(
        "query M($id: ID!) { arrayDataset(id: $id) { derivedFrom { id kind output { id } } } }",
        context_value=authenticated_context,
        variable_values={"id": str(mask.pk)},
    )
    assert not mask_lineage.errors, mask_lineage.errors
    assert mask_lineage.data["arrayDataset"]["derivedFrom"] == [], "keying a table is not a lineage claim about the mask"

    # and the edge really does exist, rooted at the mask
    assert await sync_to_async(models.Transformation.objects.filter(input=mask_system, kind=enums.TransformKindChoices.FIELD.value).exists)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_keyed_by_refuses_a_table_with_two_id_axes(authenticated_context: HttpContext):
    """One pixel holds one value, so one mask cannot supply two ids.

    `assert_field_produces` refuses this anyway, but from the field's side -- it reads as
    though the mask were at fault and suggests giving it a value axis, which would turn a
    label mask into a warp field. The fixable thing is the table's second id column, and
    the shape RFC-7 wants for a second object space is a TABLE identification on a data
    column, so the error says that.
    """
    mask = await _mask(authenticated_context)

    result = await _create(
        authenticated_context,
        "contacts",
        [
            {"name": "nucleus_id", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
            {"name": "cell_id", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
            {"name": "overlap", "dtype": "DOUBLE", "role": "ATTRIBUTE"},
        ],
        identified_by={"nucleus_id": [{"kind": "DATASET", "dataset": str(mask.pk)}]},
    )
    assert result.errors
    message = str(result.errors[0])
    assert "a source supplies one" in message
    assert "['nucleus_id', 'cell_id']" in message, "name the two it would have to supply"
    assert "kind: TABLE" in message, "point at the mechanism that does work"
    assert "value axis" not in message, "the mask is not the thing to fix"
    assert not await sync_to_async(models.TableDataset.objects.filter(name="contacts").exists)()


#
# The same relation over a different substrate. A mask materialises the id per pixel; a
# collection materialises it per geometry row, so a client that picked a surface is already
# holding one. What both share -- and the whole of what a FIELD asserts -- is that standing
# somewhere in the source's space yields an id. See `docs/field-vs-references.md`.


SHAPE_COLUMNS = [
    {"name": "object", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
    {"name": "volume", "dtype": "DOUBLE", "role": "ATTRIBUTE"},
]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_keyed_by_refuses_a_lens_and_a_table_by_construction(authenticated_context: HttpContext):
    """The union advertises two members, so the other four are a schema error, not a runtime one.

    `DerivationSourceKind` carries six; keying reuses neither the enum nor its breadth,
    because a lens owns nothing to dereference and a table is already record-land -- where
    the relation is `Column.references`. Advertising those and refusing them in a
    resolver would be a schema that says yes where the server says no.
    """
    result = await _create(authenticated_context, "shape stats", SHAPE_COLUMNS, identified_by={"object": [{"kind": "LENS", "lens": "1"}]})
    assert result.errors
    assert "LENS" in str(result.errors[0]), "refused by the enum, before any resolver runs"
    assert not await sync_to_async(models.TableDataset.objects.filter(name="shape stats").exists)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_identified_axes_lookup_does_not_repeat_per_keying_source(authenticated_context: HttpContext):
    """`identified_axes(own_system)` is a property of the table, so it is read once.

    It sat inside the per-entry loop, costing two ORM traversals per keying source, and
    nothing in the loop could change its answer.

    Counted by call rather than by query, deliberately. A query count around the whole
    mutation would also carry every unrelated read the create does, so the assertion would
    be about all of them and would drift; what is on trial is one line's position relative
    to a `for`. Patching the function *is* the direct statement of that.

    The claim is the *slope*, not the count. `assert_edge_rank` shares this definition and
    runs once per edge, so one legitimate call is added per source; the hoisted one is not.
    Measured: 2 calls for one source and 3 for two, where the un-hoisted version went 2 and
    4. Verified by ablation -- move the line back inside the loop and the delta becomes 2.
    """
    from unittest.mock import patch

    from core.logic import coordinate_system as cs_logic
    from core.logic import graph as graph_logic

    async def calls_for(label: str, masks: list) -> int:
        counter = []
        real = graph_logic.identified_axes

        def counting(system):
            counter.append(system.pk)
            return real(system)

        with patch.object(cs_logic.graph_logic, "identified_axes", counting):
            result = await _create(
                authenticated_context,
                label,
                OBJECT_COLUMNS,
                keyed_by=[{"kind": "DATASET", "dataset": str(mask.pk)} for mask in masks],
            )
        assert not result.errors, result.errors
        return len(counter)

    one = await _mask(authenticated_context, "one mask")
    two = await _mask(authenticated_context, "another mask")
    three = await _mask(authenticated_context, "a third mask")

    single = await calls_for("keyed once", [one])
    double = await calls_for("keyed twice", [two, three])

    assert double - single == 1, (
        f"one extra source added {double - single} calls, not the one `assert_edge_rank` "
        f"makes per edge ({single} -> {double}): the table's own lookup is back inside the loop"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_kind_that_cannot_key_is_refused_rather_than_raising_keyerror(authenticated_context: HttpContext):
    """The lookup into `_DERIVATION_SOURCES` was bare, so an unmapped kind was a 500.

    Reachable only through a bug -- every caller filters on `AUTHORS_EDGE` first -- but the
    keying kinds and the identifying kinds are two overlapping vocabularies whose one shared
    member is spelled differently in each: `TABLE_DATASET` in the derivation table, `TABLE`
    on a sparse axis. That is precisely the sort of near-miss that leaks, and a leak here
    was a traceback rather than a sentence.
    """
    from types import SimpleNamespace

    from core.logic import coordinate_system as cs_logic

    table = await _create(authenticated_context, "measurements", OBJECT_COLUMNS)
    assert not table.errors, table.errors
    dataset = await models.TableDataset.objects.aget(pk=table.data["createTableDataset"]["id"])
    own_system = await sync_to_async(lambda: dataset.coordinate_system)()

    entry = SimpleNamespace(kind="TABLE", source_id="1", name=None, validity=None)

    with pytest.raises(ValueError) as raised:
        await sync_to_async(cs_logic.write_key_edges)(
            info=None,
            own_system=own_system,
            keyed_by=[entry],
            name="measurements",
            ctx=None,
        )
    message = str(raised.value)
    assert "'TABLE' cannot key" in message
    assert "authors no edge" in message
    assert "TABLE_DATASET" in message, "the keyable kinds are listed"


async def _field_edges(source: models.CoordinateSystem) -> list[models.Transformation]:
    """The top-level FIELD edges out of ``source``: what mikro reads back as `attributePlans`."""
    return await sync_to_async(lambda: list(models.Transformation.objects.filter(input=source, parent__isnull=True, kind=enums.TransformKindChoices.FIELD.value).order_by("pk")))()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_keyed_by_derives_the_axis_split_from_the_two_spaces(authenticated_context: HttpContext):
    """One call, no axes stated, and the edge comes out with the split already right.

    `(t,y,x)` against `(t,i)` can only mean consume `(y,x)`, produce `i`, pass `t` through --
    the axes the two spaces share are the ones that pass through, and that is the whole rule.
    """
    mask = await _mask(authenticated_context)
    mask_system = await sync_to_async(lambda: mask.intrinsic_coordinate_system)()

    result = await _create(authenticated_context, "nuclei morphology", OBJECT_COLUMNS, identified_by={"i": [{"kind": "DATASET", "dataset": str(mask.pk)}]})
    assert not result.errors, result.errors
    table = result.data["createTableDataset"]

    (edge,) = await _field_edges(mask_system)
    assert str(edge.output_id) == table["coordinateSystem"]["id"], "the edge runs mask -> table"
    assert edge.input_axes == ["y", "x"], "derived, not stated"
    assert edge.output_axes == ["i"]
    assert edge.field_id is None, "a mask's own pixels are the map, stored as a self-field"
    assert edge.name == "nuclei labels -> nuclei morphology"
    assert edge.validity == "MANUAL", "an authored claim unless the caller says otherwise"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_keyed_by_and_derived_from_are_two_edges_in_opposite_directions(authenticated_context: HttpContext):
    """Stating both in one call writes both, and neither stands in for the other."""
    mask = await _mask(authenticated_context)
    mask_system = await sync_to_async(lambda: mask.intrinsic_coordinate_system)()

    result = await _create(
        authenticated_context,
        "nuclei morphology",
        OBJECT_COLUMNS,
        derivedFrom=[{"kind": "DATASET", "dataset": str(mask.pk), "valueRelation": "TRANSFORMED"}],
        keyed_by=[{"kind": "DATASET", "dataset": str(mask.pk), "validity": "VALIDATED"}],
    )
    assert not result.errors, result.errors
    table = result.data["createTableDataset"]
    table_system = table["coordinateSystem"]["id"]

    (lineage,) = table["derivedFrom"]
    assert lineage["kind"] == "UNMAPPABLE", "no transform stated means no geometry claimed"
    assert (lineage["input"]["id"], lineage["output"]["id"]) == (table_system, str(mask_system.pk))

    (edge,) = await _field_edges(mask_system)
    assert str(edge.output_id) == table_system
    assert edge.validity == "VALIDATED", "the caller checked the ids against the rows"
    assert str(edge.pk) != lineage["id"], "two facts, two rows"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sibling_masks_each_get_their_own_edge(authenticated_context: HttpContext):
    """`keyedBy` is a list: two masks may key one table, one edge each."""
    nuclei = await _mask(authenticated_context, "nuclei labels")
    cells = await _mask(authenticated_context, "cell labels")
    result = await _create(
        authenticated_context,
        "object morphology",
        OBJECT_COLUMNS,
        keyed_by=[{"kind": "DATASET", "dataset": str(nuclei.pk)}, {"kind": "DATASET", "dataset": str(cells.pk)}],
    )
    assert not result.errors, result.errors
    for mask in (nuclei, cells):
        system = await sync_to_async(lambda: mask.intrinsic_coordinate_system)()
        assert len(await _field_edges(system)) == 1, f"one edge rooted at {system.pk}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_referenced_index_axis_is_identified_and_the_field_need_not_produce_it(authenticated_context: HttpContext):
    """The product-space case: a row identified by a *pair*, and a mask can only supply one; the other is a TABLE reference."""
    mask = await _mask(authenticated_context)
    cells = await _create(
        authenticated_context,
        "cells",
        [
            {"name": "cell_id", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
            {"name": "area", "dtype": "DOUBLE", "role": "ATTRIBUTE"},
        ],
    )
    assert not cells.errors, cells.errors

    result = await _create(
        authenticated_context,
        "contacts",
        [
            {"name": "nucleus_id", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX"},
            {"name": "cell_id", "dtype": "BIGINT", "role": "COORDINATE", "axisType": "INDEX", "references": cells.data["createTableDataset"]["id"]},
            {"name": "overlap", "dtype": "DOUBLE", "role": "ATTRIBUTE"},
        ],
        identified_by={"nucleus_id": [{"kind": "DATASET", "dataset": str(mask.pk)}]},
    )
    assert not result.errors, result.errors
    table = result.data["createTableDataset"]
    assert [axis["name"] for axis in table["coordinateSystem"]["axes"]] == ["nucleus_id", "cell_id"], "both are coordinates: the row is the pair"
    referenced = {column["name"]: column["references"] for column in table["columns"]}
    assert referenced["cell_id"]["name"] == "cells" and referenced["nucleus_id"] is None

    (edge,) = await _field_edges(await sync_to_async(lambda: mask.intrinsic_coordinate_system)())
    assert edge.output_axes == ["nucleus_id"], "the identified axis is accounted for, so the edge produces only the one it supplies"

    from core.logic import graph as graph_logic

    contacts = await models.TableDataset.objects.aget(pk=table["id"])
    assert await sync_to_async(graph_logic.product_space_tables)([contacts]) == {contacts.pk}
