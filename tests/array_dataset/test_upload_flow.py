"""End-to-end Zarr upload flow against the schema:

requestZarrUpload -> (write a real Zarr v3 array to RustFS through obstore using
the issued grant) -> finishZarrUpload -> createArrayDataset.

This complements test_array_dataset (which hand-seeds zarr.json): here the
store is populated by an actual client-style upload, validating the datalayer's
grant / finish / get_zarr_metadata chain.
"""

import pytest

from core.models import DataArray, Folder
from datalayer.models import ZarrStore

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


REQUEST_ZARR_UPLOAD = """
mutation ($input: RequestZarrUploadInput!) {
  requestZarrUpload(input: $input) {
    accessKey
    secretKey
    sessionToken
    bucket
    key
    path
    store
  }
}
"""

FINISH_ZARR_UPLOAD = """
mutation ($input: FinishZarrUploadInput!) {
  finishZarrUpload(input: $input) { id }
}
"""

REQUEST_ZARR_ACCESS = """
mutation ($input: RequestZarrAccessInput!) {
  requestZarrAccess(input: $input) {
    accessKey
    secretKey
    sessionToken
    bucket
    key
    path
    store
  }
}
"""

CREATE_ARRAY_DATASET = """
mutation ($input: CreateArrayDatasetInput!) {
  createArrayDataset(input: $input) { id name shape folder { name } }
}
"""


async def test_zarr_upload_to_array_dataset_flow(
    aexecute, authenticated_context, upload_zarr_to_grant, read_zarr_from_grant
):
    # 1. Request an upload grant -> server creates the ZarrStore + returns S3 creds.
    grant_res = await aexecute(REQUEST_ZARR_UPLOAD, {"input": {"shape": [4, 4], "chunks": [4, 4]}})
    assert not grant_res.errors, grant_res.errors
    grant = grant_res.data["requestZarrUpload"]
    assert grant["bucket"] == "zarr"
    assert grant["store"]

    # 2. Upload a real Zarr v3 array to MinIO through obstore, using the grant.
    await upload_zarr_to_grant(grant, (4, 4), (4, 4))

    # 3. Finish the upload -> server reads zarr.json and marks the store populated.
    fin = await aexecute(FINISH_ZARR_UPLOAD, {"input": {"storeId": grant["store"]}})
    assert not fin.errors, fin.errors
    assert fin.data["finishZarrUpload"]["id"]
    store = await ZarrStore.objects.aget(id=grant["store"])
    assert store.populated
    assert store.shape == [4, 4]

    # 4. Create an array dataset from that store, filed in a folder of our choosing.
    ds = await Folder.objects.acreate(
        name="ds",
        creator=authenticated_context.request.user,
        organization=authenticated_context.request.organization,
        membership=authenticated_context.request.membership,
    )
    res = await aexecute(
        CREATE_ARRAY_DATASET,
        # Nothing in the bytes says (t, c) rather than (sweep, t), so the axes are always declared.
        {"input": {"data": grant["store"], "scales": [], "name": "uploaded", "folder": str(ds.id), "axes": [{"name": "t", "type": "TIME"}, {"name": "c", "type": "CHANNEL"}]}},
    )
    assert not res.errors, res.errors
    assert res.data["createArrayDataset"] == {"id": res.data["createArrayDataset"]["id"], "name": "uploaded", "shape": [4, 4], "folder": {"name": "ds"}}

    level_0 = await DataArray.objects.aget(dataset__name="uploaded", level=0)
    assert str(level_0.store_id) == grant["store"], "the store belongs to the level, not to the dataset"

    # 5. Request read access for the level's store and pull the array back from S3.
    import numpy as np

    acc = await aexecute(REQUEST_ZARR_ACCESS, {"input": {"storeId": grant["store"]}})
    assert not acc.errors, acc.errors
    access = acc.data["requestZarrAccess"]
    assert access["bucket"] == "zarr"

    data = await read_zarr_from_grant(access)
    assert data.shape == (4, 4)
    assert data.tolist() == np.arange(16, dtype="float64").reshape(4, 4).tolist()


REQUEST_GENERAL_ZARR_ACCESS = """
mutation ($input: RequestGeneralZarrAccessInput!) {
  requestGeneralZarrAccess(input: $input) {
    accessKey
    secretKey
    sessionToken
    bucket
  }
}
"""


async def test_request_general_zarr_access(aexecute):
    # Org-wide read grant: no store needed, just issues credentials.
    res = await aexecute(REQUEST_GENERAL_ZARR_ACCESS, {"input": {}})
    assert not res.errors, res.errors
    grant = res.data["requestGeneralZarrAccess"]
    assert grant["bucket"] == "zarr"
    assert grant["accessKey"]


# --- negative ----------------------------------------------------------------


async def test_finish_zarr_upload_before_upload(aexecute):
    # Finish without ever uploading -> no zarr.json -> get_zarr_metadata raises.
    grant_res = await aexecute(REQUEST_ZARR_UPLOAD, {"input": {"shape": [4, 4], "chunks": [4, 4]}})
    assert not grant_res.errors, grant_res.errors
    grant = grant_res.data["requestZarrUpload"]

    fin = await aexecute(FINISH_ZARR_UPLOAD, {"input": {"storeId": grant["store"]}})
    assert fin.errors
