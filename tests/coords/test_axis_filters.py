"""`timed` and `hasAxisTypes`: one axis question, asked of every container and of a space itself.

A picker that wants "the clocks" or "the timed data" used to fetch one page and keep the ones
with a TIME axis on the client -- so the page came back short, or empty while clocks existed.
These are the server answering it, through one subquery (`core.filters._has_axis_type_q`), so an
array dataset, a sparse dataset, a table, an annotation collection and a space never disagree
about what "timed" means.
"""

import pytest

from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


ARRAYS = """
query Arrays($timed: Boolean) {
  arrayDatasets(filters: { timed: $timed }) { id }
}
"""

COLLECTIONS = """
query Collections($timed: Boolean) {
  annotationCollections(filters: { timed: $timed }) { id }
}
"""

SYSTEMS = """
query Systems($types: [AxisType!], $limit: Int) {
  coordinateSystems(filters: { hasAxisTypes: $types }, pagination: { limit: $limit }) { id }
}
"""

CREATE_ANNOTATION_COLLECTION = """
mutation Create($input: CreateAnnotationCollectionInput!) {
  createAnnotationCollection(input: $input) { id }
}
"""


async def _ids(aexecute, query: str, variables: dict, key: str) -> set[str]:  # noqa: ANN001
    result = await aexecute(query, variables)
    assert not result.errors, result.errors
    return {row["id"] for row in result.data[key]}


async def test_array_datasets_split_on_a_time_axis(aexecute, authenticated_context):
    recording = await seed.create_dataset(authenticated_context, "Recording")  # t, c
    image = await seed.create_array_dataset(authenticated_context, "Image")  # c, y, x

    timed = await _ids(aexecute, ARRAYS, {"timed": True}, "arrayDatasets")
    untimed = await _ids(aexecute, ARRAYS, {"timed": False}, "arrayDatasets")
    everything = await _ids(aexecute, ARRAYS, {"timed": None}, "arrayDatasets")

    assert str(recording.pk) in timed and str(recording.pk) not in untimed
    assert str(image.pk) in untimed and str(image.pk) not in timed
    assert {str(recording.pk), str(image.pk)} <= everything, "null leaves the list alone"


async def test_annotation_collections_split_on_a_time_axis(aexecute):
    events = await aexecute(CREATE_ANNOTATION_COLLECTION, {"input": {"name": "Epochs", "axes": [{"name": "t", "type": "TIME"}]}})
    shapes = await aexecute(CREATE_ANNOTATION_COLLECTION, {"input": {"name": "Sites", "axes": [{"name": "y", "type": "SPACE"}, {"name": "x", "type": "SPACE"}]}})
    assert not events.errors and not shapes.errors, (events.errors, shapes.errors)
    events_id = events.data["createAnnotationCollection"]["id"]
    shapes_id = shapes.data["createAnnotationCollection"]["id"]

    assert await _ids(aexecute, COLLECTIONS, {"timed": True}, "annotationCollections") == {events_id}
    assert await _ids(aexecute, COLLECTIONS, {"timed": False}, "annotationCollections") == {shapes_id}


async def test_clocks_are_found_past_the_first_page_of_spaces(aexecute, authenticated_context):
    """The ClockPicker's case: a page of spaces with no TIME axis must not hide the clock."""
    for index in range(5):
        await seed.create_array_dataset(authenticated_context, f"Image {index}")  # untimed grids, made first
    clock = await seed.create_clock(authenticated_context, "Session")

    page = await _ids(aexecute, SYSTEMS, {"types": ["TIME"], "limit": 2}, "coordinateSystems")

    assert str(clock.pk) in page, "the filter runs before the page is cut"


async def test_has_axis_types_on_a_space_is_all_of(aexecute, authenticated_context):
    recording = await seed.create_dataset(authenticated_context, "Recording")  # t, c
    clock = await seed.create_clock(authenticated_context, "Session")  # t only

    both = await _ids(aexecute, SYSTEMS, {"types": ["TIME", "CHANNEL"], "limit": None}, "coordinateSystems")

    assert str(recording.coordinate_system_id) in both
    assert str(clock.pk) not in both, "a clock has TIME but no CHANNEL axis"
