from kante.types import Info
from typing import cast
from datalayer import inputs, types
from datalayer.datalayer import get_current_datalayer
from datalayer import models

def request_zarr_upload(
    info: Info, input: inputs.RequestZarrUploadInput
) -> types.ZarrUploadGrant:
    """Request temporary S3 upload credentials for a Zarr store."""
    del info
    dl = get_current_datalayer()
    input_model = getattr(input, "to_pydantic")()
    return types.ZarrUploadGrant.from_pydantic(dl.generate_zarr_upload_grant(input_model))


def finish_zarr_upload(
    info: Info, input: inputs.FinishZarrUploadInput
) -> types.ZarrStore:
    """Mark the ZarrStore as populated after a successful upload."""
    del info
    dl = get_current_datalayer()
    input_model = getattr(input, "to_pydantic")()
    return cast(types.ZarrStore, dl.finish_zarr_upload(input_model))

def request_zarr_access(
    info: Info, input: inputs.RequestZarrAccessInput
) -> types.ZarrAccessGrant:
    """Request temporary S3 read credentials for a Zarr store."""
    del info
    dl = get_current_datalayer()
    
    model = input.to_pydantic()
    
    store = models.ZarrStore.objects.get(id=model.store_id)
    return types.ZarrAccessGrant.from_pydantic(dl.generate_zarr_access_grant(store))