import strawberry
from strawberry.scalars import JSON
from datalayer import models
from kante.types import Info
import kante
from typing import cast
from datalayer import base_models
from datalayer.datalayer import get_current_datalayer


@kante.pydantic_type(base_models.BigFileAccessGrant, description="Temporary S3 credentials for reading a big file.")
class BigFileAccessGrant:
    """Temporary S3 credentials for a big file."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    region: str

    bucket: str
    key: str
    path: str
    expires_in: int
    store: str | None


@kante.pydantic_type(base_models.MediaAccessGrant, description="Temporary S3 credentials for reading a media object.")
class MediaAccessGrant:
    """Temporary S3 credentials for a media object."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    region: str
    bucket: str
    key: str
    path: str
    expires_in: int
    store: str | None


@kante.pydantic_type(base_models.GeneralMediaAccessGrant, description="Temporary S3 credentials for reading a media object.")
class GeneralMediaAccessGrant:
    """Temporary S3 credentials for a media object."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    region: str
    bucket: str
    path: str
    expires_in: int
    store: str | None


@kante.pydantic_type(base_models.ZarrAccessGrant, description="Temporary S3 credentials for reading a Zarr store.")
class ZarrAccessGrant:
    """Temporary S3 credentials for a Zarr store."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    region: str

    bucket: str
    key: str
    path: str
    expires_in: int
    store: str | None


@kante.pydantic_type(base_models.GeneralZarrAccessGrant, description="Temporary S3 credentials for reading a Zarr store.")
class GeneralZarrAccessGrant:
    """Temporary S3 credentials for a Zarr store."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    region: str
    bucket: str
    path: str
    expires_in: int
    store: str | None


@kante.pydantic_type(base_models.GeneralZarrAccessGrant, description="Temporary S3 credentials for reading a Zarr store.")
class GeneralParquetAccessGrant:
    """Temporary S3 credentials for a Zarr store."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    region: str
    bucket: str
    path: str
    expires_in: int
    store: str | None


@kante.pydantic_type(base_models.ParquetAccessGrant, description="Temporary S3 credentials for reading a parquet object.")
class ParquetAccessGrant:
    """Temporary S3 credentials for a parquet object."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    region: str
    bucket: str
    key: str
    path: str
    expires_in: int
    store: str | None


@kante.pydantic_type(base_models.MediaUploadGrant, description="A presigned PUT grant for uploading a media object.")
class MediaUploadGrant:
    """A presigned PUT grant for a media upload."""

    region: str
    status: str
    access_key: str
    secret_key: str
    session_token: str
    bucket: str
    key: str
    path: str
    expires_in: int
    max_bytes: int
    original_file_name: str | None
    upload_file_name: str
    upload_content_type: str | None
    upload_form_field: str
    store: str


@kante.pydantic_type(base_models.BigFileUploadGrant, description="Temporary S3 credentials for uploading a big file.")
class BigFileUploadGrant:
    """Temporary S3 credentials for a big file upload."""

    region: str
    status: str
    access_key: str
    secret_key: str
    session_token: str
    bucket: str
    key: str
    path: str
    expires_in: int
    max_bytes: int
    original_file_name: str | None
    upload_file_name: str
    upload_content_type: str | None
    upload_form_field: str
    store: str


@kante.pydantic_type(base_models.ZarrUploadGrant, description="Temporary S3 credentials for uploading a Zarr store.")
class ZarrUploadGrant:
    """Temporary S3 credentials for a Zarr upload."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    bucket: str
    key: str
    path: str
    action: str
    expires_in: int
    max_bytes: int
    original_file_name: str | None
    upload_file_name: str
    upload_content_type: str | None
    upload_form_field: str
    store: str


@kante.pydantic_type(base_models.ParquetUploadGrant, description="Temporary S3 credentials for uploading a parquet store.")
class ParquetUploadGrant:
    """Temporary S3 credentials for a parquet upload."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    bucket: str
    key: str
    path: str
    action: str
    expires_in: int
    max_bytes: int
    original_file_name: str | None
    upload_file_name: str
    upload_content_type: str | None
    upload_form_field: str
    store: str


@kante.django_type(
    models.BigFileStore,
    description="A BigFileStore represents a large object stored behind the S3 datalayer.",
)
class BigFileStore:
    """A large object stored behind the S3 datalayer."""

    id: strawberry.auto
    path: str
    bucket: str
    key: str
    original_file_name: str | None
    content_type: str | None

    @strawberry.field(description="Get temporary S3 read credentials for the object.")
    def access_grant(self, info: Info, host: str | None = None) -> BigFileAccessGrant:
        """Return a signed read grant for the big file."""
        del info, host
        datalayer = get_current_datalayer()
        grant = cast(models.BigFileStore, self).get_access_grant(datalayer=datalayer)
        return BigFileAccessGrant.from_pydantic(grant)

    @strawberry.field()
    def presigned_url(self, info: Info) -> str:
        """Compatibility field returning the canonical S3 object path."""
        datalayer = get_current_datalayer()
        return cast(models.BigFileStore, self).get_presigned_url(datalayer=datalayer)


@kante.django_type(models.MediaStore)
class MediaStore:
    """A media object stored behind the S3 datalayer."""

    id: strawberry.auto
    path: str
    bucket: str
    key: str
    original_file_name: str | None
    content_type: str | None

    @kante.django_field(description="Get temporary S3 read credentials for the media object.")
    def access_grant(self, info: Info, host: str | None = None) -> MediaAccessGrant:
        """Return a signed read grant for the media object."""
        del info, host
        datalayer = get_current_datalayer()
        grant = cast(models.MediaStore, self).get_access_grant(datalayer=datalayer)
        return MediaAccessGrant(**grant.model_dump())

    @kante.django_field(description="Compatibility field returning the canonical S3 object path.")
    def presigned_url(self, info: Info, host: str | None = None) -> str:
        """Compatibility field returning the canonical S3 object path."""
        datalayer = get_current_datalayer()
        return cast(models.MediaStore, self).get_presigned_url(datalayer=datalayer, host=host)


@kante.django_type(models.ZarrStore)
class ZarrStore:
    """A Zarr object stored behind the S3 datalayer."""

    id: strawberry.auto
    path: str
    bucket: str
    key: str
    shape: list[int]
    chunks: list[int]
    version: str | None
    dtype: str | None
    dimension_names: list[str | None] | None
    fill_value: JSON
    attributes: JSON | None
    storage_transformers: JSON | None
    chunk_key_encoding: JSON | None
    codecs: JSON | None

    @kante.django_field(description="Get temporary S3 read credentials for the Zarr object.")
    def access_grant(self, info: Info, host: str | None = None) -> ZarrAccessGrant:
        """Return a signed read grant for the Zarr store."""
        del info, host
        datalayer = get_current_datalayer()
        grant = cast(models.ZarrStore, self).get_access_grant(datalayer=datalayer)
        return ZarrAccessGrant(**grant.model_dump())


@kante.django_type(models.ParquetStore)
class ParquetStore:
    """A parquet object stored behind the S3 datalayer."""

    id: strawberry.auto
    path: str
    bucket: str
    key: str
    original_file_name: str | None
    content_type: str | None

    @kante.django_field(description="Get temporary S3 read credentials for the parquet object.")
    def access_grant(self, info: Info, host: str | None = None) -> ParquetAccessGrant:
        """Return a signed read grant for the Zarr store."""
        del info, host
        datalayer = get_current_datalayer()
        grant = cast(models.ParquetStore, self).get_access_grant(datalayer=datalayer)
        return ParquetAccessGrant(**grant.model_dump())

    @kante.django_field(description="Compatibility field returning the canonical S3 object path.")
    def presigned_url(self, info: Info, host: str | None = None) -> str:
        """Compatibility field returning the canonical S3 object path."""
        datalayer = get_current_datalayer()
        return cast(models.ParquetStore, self).get_presigned_url(datalayer=datalayer, host=host)
