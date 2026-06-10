from typing import Literal, Optional, cast

from pydantic import BaseModel, JsonValue


class RequestMediaUploadInput(BaseModel):
    """Request temporary S3 upload credentials for a media object."""

    original_file_name: str
    file_size: Optional[int] = None
    content_type: Optional[str] = None


class FinishMediaUploadInput(BaseModel):
    """Mark a MediaStore as populated after a successful upload."""

    store_id: str
    valid: bool = True


class RequestMediaAccessInput(BaseModel):
    """Request temporary S3 access credentials for a media object."""

    store_id: str


class RequestGeneralMediaAccessInput(BaseModel):
    """Request temporary S3 access credentials for media objects in the organization."""

    expires_in: Optional[int] = None


class RequestGeneralZarrAccessInput(BaseModel):
    """Request temporary S3 access credentials for media objects in the organization."""

    expires_in: Optional[int] = None


class RequestGeneralParquetAccessInput(BaseModel):
    """Request temporary S3 access credentials for media objects in the organization."""

    expires_in: Optional[int] = None


class RequestBigFileUploadInput(BaseModel):
    """Request temporary S3 upload credentials for a big file."""

    original_file_name: str
    file_size: Optional[int] = None
    content_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None


class FinishBigFileUploadInput(BaseModel):
    """Mark a BigFileStore as populated after a successful upload."""

    store_id: str
    valid: bool = True


class RequestBigFileAccessInput(BaseModel):
    """Request temporary S3 access credentials for a media object."""

    store_id: str


class RequestZarrUploadInput(BaseModel):
    """Request temporary S3 upload credentials for a Zarr store."""

    shape: Optional[list[int]] = None
    chunks: Optional[list[int]] = None
    version: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None


class FinishZarrUploadInput(BaseModel):
    """Mark a ZarrStore as populated after a successful upload."""

    store_id: str
    valid: bool = True


class RequestZarrAccessInput(BaseModel):
    """Request temporary S3 access credentials for a media object."""

    store_id: str


class ZarrMetadata(BaseModel):
    """Structured metadata discovered from a Zarr store."""

    zarr_format: int
    node_type: Literal["array"]
    shape: list[int]
    data_type: JsonValue
    chunk_grid: JsonValue
    chunk_key_encoding: JsonValue
    fill_value: JsonValue
    codecs: list[JsonValue]
    attributes: dict[str, JsonValue] | None = None
    storage_transformers: list[JsonValue] | None = None
    dimension_names: list[str | None] | None = None

    @property
    def version(self) -> str:
        """Return the Zarr format version as a string for legacy callers."""

        return str(self.zarr_format)

    @property
    def dtype(self) -> str | None:
        """Return the data type identifier when it is a plain string."""

        return self.data_type if isinstance(self.data_type, str) else None

    @property
    def chunks(self) -> list[int] | None:
        """Return the regular chunk shape for callers using the legacy field name."""

        if not isinstance(self.chunk_grid, dict):
            return None

        configuration = self.chunk_grid.get("configuration")
        if not isinstance(configuration, dict):
            return None

        chunk_shape = configuration.get("chunk_shape")
        if not isinstance(chunk_shape, list) or not all(isinstance(item, int) for item in chunk_shape):
            return None

        return cast(list[int], chunk_shape)


class RequestParquetUploadInput(BaseModel):
    """Request temporary S3 upload credentials for a Parquet store."""

    content_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None


class FinishParquetUploadInput(BaseModel):
    """Mark a ParquetStore as populated after a successful upload."""

    store_id: str
    valid: bool = True


class RequestParquetAccessInput(BaseModel):
    """Request temporary S3 access credentials for a media object."""

    store_id: str


class AccessGrant(BaseModel):
    """Temporary S3 credentials scoped to a datalayer action."""

    status: str = "granted"
    access_key: str
    secret_key: str
    session_token: str
    region: str
    bucket: str
    key: str
    path: str
    expires_in: int
    store: str | None = None


class GeneralAccessGrant(BaseModel):
    """Temporary S3 credentials for an existing media object, without a store reference."""

    status: str = "granted"
    access_key: str
    secret_key: str
    session_token: str
    region: str
    bucket: str
    expires_in: int


class GeneralMediaAccessGrant(GeneralAccessGrant):
    """Temporary S3 credentials for an existing media object, without a store reference."""


class GeneralZarrAccessGrant(GeneralAccessGrant):
    """Temporary S3 credentials for an existing media object, without a store reference."""


class GeneralParquetAccessGrant(GeneralAccessGrant):
    """Temporary S3 credentials for an existing media object, without a store reference."""


class BigFileAccessGrant(AccessGrant):
    """Temporary S3 credentials for an existing big file."""


class MediaAccessGrant(AccessGrant):
    """Temporary S3 credentials for an existing media object."""


class ZarrAccessGrant(AccessGrant):
    """Temporary S3 credentials for an existing Zarr store."""


class ParquetAccessGrant(AccessGrant):
    """Temporary S3 credentials for an existing parquet store."""


class BaseUploadGrant(AccessGrant):
    """Temporary S3 credentials for uploads bound to a specific store."""

    region: str
    max_bytes: int
    original_file_name: str | None = None
    upload_file_name: str
    upload_content_type: str | None = None
    upload_form_field: str = "file"


class MediaUploadGrant(BaseUploadGrant):
    """A presigned PUT grant for a media upload."""


class BigFileUploadGrant(BaseUploadGrant):
    """Temporary S3 credentials for a big file upload."""


class ZarrUploadGrant(BaseUploadGrant):
    """Temporary S3 credentials for a Zarr upload."""


class ParquetUploadGrant(BaseUploadGrant):
    """Temporary S3 credentials for a parquet upload."""
