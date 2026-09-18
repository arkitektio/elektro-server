"""`inputAxes` next to `input { ... }` on one edge.

Both prefetch the edge's `input`: the axis fields through a hint, the relation through the
optimizer, which gives it `CoordinateSystem`'s scoped queryset. While the hint was the string
`"input__axes"`, Django walked `input` once without a queryset and then refused the scoped
one -- "'input' lookup was already seen with a different queryset" -- so any client asking
for an edge's endpoints *and* its axis order got an error instead of either.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

EDGE = "id inputAxes outputAxes input { id name } output { id name axes { name } }"

TOP_LEVEL = f"query {{ transformations {{ {EDGE} }} }}"

CHILDREN = f"""
query {{
  transformations {{
    id
    ... on SequenceTransformation {{ transformations {{ {EDGE} }} }}
  }}
}}
"""


async def _sequence(ctx) -> tuple[models.CoordinateSystem, models.CoordinateSystem]:  # noqa: ANN001
    source = await seed.create_world(ctx, "Source", seed.ZYX_WORLD_AXES)
    target = await seed.create_world(ctx, "Target", seed.ZYX_WORLD_AXES)

    def build() -> None:
        owned = {"creator": ctx.request.user, "organization": ctx.request.organization}
        sequence = models.Transformation.objects.create(kind="SEQUENCE", params={}, input=source, output=target, **owned)
        models.Transformation.objects.create(kind="SCALE", params={"scale": [1.0, 2.0, 3.0]}, input=source, output=target, parent=sequence, order=0, **owned)

    await sync_to_async(build)()
    return source, target


def _edges(data: dict) -> list[dict]:
    """The edges carrying `EDGE`'s selection: every edge, or only the children of the sequence."""
    listed = data["transformations"]
    children = [child for edge in listed for child in edge.get("transformations", [])]
    return children or listed


@pytest.mark.parametrize("query", [TOP_LEVEL, CHILDREN], ids=["edge", "child of a sequence"])
async def test_an_edge_reads_its_endpoints_and_their_axis_order_together(aexecute, authenticated_context, query: str):
    source, target = await _sequence(authenticated_context)

    result = await aexecute(query)

    assert not result.errors, result.errors
    edges = _edges(result.data)
    assert edges, "the query reached an edge"
    for edge in edges:
        assert edge["input"] == {"id": str(source.pk), "name": source.name}
        assert edge["output"]["id"] == str(target.pk)
        assert edge["inputAxes"] == edge["outputAxes"] == ["z", "y", "x"]
        assert [axis["name"] for axis in edge["output"]["axes"]] == ["z", "y", "x"]
