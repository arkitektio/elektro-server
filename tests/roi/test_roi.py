"""ROI mutations executed against the schema (createRoi/updateRoi/deleteRoi)."""

import pytest

from core.models import ROI

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


CREATE_ROI = """
mutation ($input: RoiInput!) {
  createRoi(input: $input) { id kind }
}
"""

UPDATE_ROI = """
mutation ($input: UpdateRoiInput!) {
  updateRoi(input: $input) { id label }
}
"""

DELETE_ROI = """
mutation ($input: DeleteRoiInput!) {
  deleteRoi(input: $input)
}
"""


async def _make_roi(ctx, trace):
    return await ROI.objects.acreate(
        trace=trace, creator=ctx.request.user, vectors=[[0, 0], [1, 1]], kind="spike"
    )


async def test_create_roi(aexecute, make_trace):
    trace = await make_trace()
    res = await aexecute(
        CREATE_ROI,
        {"input": {"trace": str(trace.id), "vectors": [[0, 0], [2, 3]], "kind": "SPIKE"}},
    )
    assert not res.errors, res.errors
    assert await ROI.objects.filter(trace=trace).aexists()


async def test_update_roi(aexecute, authenticated_context, make_trace):
    trace = await make_trace()
    roi = await _make_roi(authenticated_context, trace)
    res = await aexecute(UPDATE_ROI, {"input": {"roi": str(roi.id), "label": "renamed"}})
    assert not res.errors, res.errors
    assert res.data["updateRoi"]["label"] == "renamed"
    await roi.arefresh_from_db()
    assert roi.label == "renamed"


async def test_delete_roi(aexecute, authenticated_context, make_trace):
    trace = await make_trace()
    roi = await _make_roi(authenticated_context, trace)
    res = await aexecute(DELETE_ROI, {"input": {"id": str(roi.id)}})
    assert not res.errors, res.errors
    assert res.data["deleteRoi"] == str(roi.id)
    assert not await ROI.objects.filter(id=roi.id).aexists()


# --- negatives ---------------------------------------------------------------


async def test_create_roi_unknown_trace(aexecute):
    res = await aexecute(
        CREATE_ROI, {"input": {"trace": "999999", "vectors": [[0, 0]], "kind": "SPIKE"}}
    )
    assert res.errors


async def test_delete_roi_not_found(aexecute):
    res = await aexecute(DELETE_ROI, {"input": {"id": "999999"}})
    assert res.errors
