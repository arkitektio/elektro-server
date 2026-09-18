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


class RequestGeneralSparseAccessInput(BaseModel):
    """Request temporary S3 access credentials for sparse stores in the organization."""

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


class RequestSparseUploadInput(BaseModel):
    """Request temporary S3 upload credentials for a sparse store.

    Carries nothing about the matrix, for the reason its fabriks sibling carries nothing about
    the meshes: a sparse store is *self-describing*. The writer states the encoding, the shape
    and the chunking in the group it uploads, and the server reads them back when the upload is
    finished. Declaring them here would be a second statement of the same facts, free to
    disagree with the bytes.

    Note this is the one place it differs from `RequestZarrUploadInput`, which does take
    `shape` and `chunks`: that grant describes a single array whose metadata a caller may
    legitimately know in advance, where this one describes a group of three whose relationship
    is the whole content.
    """

    host: Optional[str] = None
    port: Optional[int] = None


class FinishSparseUploadInput(BaseModel):
    """Mark a SparseStore as populated after a successful upload."""

    store_id: str
    valid: bool = True


class RefreshSparseUploadInput(BaseModel):
    """Reissue upload credentials for a sparse store whose upload is still in flight.

    Present for the same reason `RefreshZarrUploadInput` is: a prefix is written incrementally,
    and a session token can expire in the middle of a matrix that takes minutes to upload.
    """

    store_id: str


class RequestSparseAccessInput(BaseModel):
    """Request temporary S3 access credentials for a sparse store."""

    store_id: str


class SparseLayoutMetadata(BaseModel):
    """One stored layout of a sparse matrix, as its own group declares it.

    ``encoding`` is the whole of what the two layouts differ in -- ``csr_matrix`` means
    ``indptr`` indexes axis 0, ``csc_matrix`` axis 1 -- and therefore which question this layout
    answers in one contiguous read. It is never taken from a caller.
    """

    path: str
    encoding: str
    encoding_version: Optional[str] = None
    indexed_axis: int
    #: The axes this layout did *not* compress, in the order ``indices`` was raveled over them.
    #: At rank two it has one member and says nothing; above it, it is the one fact in the format
    #: that cannot be recovered from the bytes -- a wrong one does not fail, it puts every value
    #: in a different cell -- which is why the writer states it and the reader checks it.
    index_order: list[int]
    nnz: int
    dtype: str
    chunks: JsonValue = None
    #: Whether a slice of this layout can be fetched as an exact byte range rather than as whole
    #: chunks. **Derived, never declared** -- true exactly when each array is one uncompressed
    #: chunk, so the stored object is the raw buffer and `indptr` names byte offsets into it.
    #:
    #: False is the ordinary case and not a defect: the default trades bytes for reuse, because on
    #: an object store the cost is requests, and a chunk is a cache unit that the next lookup along
    #: an adjacent slice hits again.
    range_readable: bool = False


class SparseMetadata(BaseModel):
    """What a sparse store states about itself, as discovered from its own zarr metadata.

    The sparse analogue of :class:`ZarrMetadata` and :class:`FabriksMetadata`, and read for the
    same reason: a fact derived from the artifact cannot be declared wrong.

    Unlike those two it is *nested*, because one matrix is one upload and may hold a layout per
    axis. ``shape`` is the store's, at whatever rank it has, and every layout is checked against
    it; everything that differs between layouts lives in :class:`SparseLayoutMetadata`.

    **Two axes is one case, not the definition.** A layout is one axis made contiguous, so an
    array of rank *n* has up to *n* of them -- a (object, feature, timepoint) matrix can answer
    "this object", "this feature" and "this timepoint" in one contiguous read each.

    ``spec`` comes from the root block, which the writer lands **last**. That ordering is the
    only reason an interrupted upload is detectable at all: zarr writes an array's metadata
    ahead of its chunks and substitutes the fill value for a chunk it cannot fetch, so a torn
    prefix otherwise reads back as the right number of zeros and raises nothing.
    """

    spec: str
    shape: list[int]
    layouts: list[SparseLayoutMetadata]


class ParquetColumn(BaseModel):
    """One column, as the file itself declares it.

    The three fields are the first three of a DuckDB ``DESCRIBE`` row. ``type`` is therefore a
    DuckDB type name (``BIGINT``, ``DOUBLE``, ``VARCHAR``) -- the same vocabulary a caller used
    to have to guess at, now read rather than declared.
    """

    name: str
    type: str
    nullable: bool


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


class GeneralSparseAccessGrant(GeneralAccessGrant):
    """Temporary S3 credentials for existing sparse stores, without a store reference."""


class BigFileAccessGrant(AccessGrant):
    """Temporary S3 credentials for an existing big file."""


class MediaAccessGrant(AccessGrant):
    """Temporary S3 credentials for an existing media object."""


class ZarrAccessGrant(AccessGrant):
    """Temporary S3 credentials for an existing Zarr store."""


class ParquetAccessGrant(AccessGrant):
    """Temporary S3 credentials for an existing parquet store."""


class SparseAccessGrant(AccessGrant):
    """Temporary S3 credentials for an existing sparse store.

    Covers the whole prefix, so one grant reads the group's attributes and all three of its
    arrays -- which is the minimum that answers anything, since a lookup needs `indptr` before
    it knows which range of `data` to fetch.
    """


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


class SparseUploadGrant(BaseUploadGrant):
    """Temporary S3 credentials for a sparse upload.

    Scoped to the prefix and permitted to read back and delete inside it, because the three
    arrays are written incrementally.
    """
