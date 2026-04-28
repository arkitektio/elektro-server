from kante.types import Info
from typing import cast
from datalayer import inputs, types
from datalayer.datalayer import get_current_datalayer
from datalayer import models

def request_bigfile_upload(
    info: Info, input: inputs.RequestBigFileUploadInput
) -> types.BigFileUploadGrant:
    """Request temporary S3 upload credentials for a big file."""
    del info
    dl = get_current_datalayer()
    input_model = getattr(input, "to_pydantic")()
    return types.BigFileUploadGrant.from_pydantic(dl.generate_bigfile_upload_grant(input_model))


def finish_bigfile_upload(
    info: Info, input: inputs.FinishBigFileUploadInput
) -> types.BigFileStore:
    """Mark the BigFileStore as populated after a successful upload."""
    del info
    dl = get_current_datalayer()
    input_model = getattr(input, "to_pydantic")()
    return cast(types.BigFileStore, dl.finish_bigfile_upload(input_model))


def request_bigfile_access(
    info: Info, input: inputs.RequestBigFileAccessInput
) -> types.BigFileAccessGrant:
    """Request temporary S3 read credentials for a big file."""
    del info
    dl = get_current_datalayer()
    model = input.to_pydantic()
    
    store = models.BigFileStore.objects.get(id=model.store_id)
    return types.BigFileAccessGrant.from_pydantic(dl.generate_bigfile_access_grant(store))