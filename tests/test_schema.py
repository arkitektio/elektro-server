"""Schema smoke tests: the schema must build and expose the datalayer
scalars and mutations wired through ``StrawberryConfig.scalar_map``.
No database required."""

from elektro_server.schema import schema


def test_schema_builds():
    sdl = schema.as_str()
    assert sdl


def test_datalayer_scalars_registered():
    # BigFileLike is referenced by core mutations, so it must be emitted via the
    # StrawberryConfig.scalar_map wiring. An array reference is mikro's ArrayLike: the data
    # layer is mikro's by name, and the old TraceLike is gone with `fromTraceLike`.
    sdl = schema.as_str()
    assert "scalar TraceLike" not in sdl
    assert sdl.count("scalar ArrayLike") == 1, "one scalar for 'a store holding an array'"
    for scalar_name in ["scalar ArrayLike", "scalar BigFileLike"]:
        assert scalar_name in sdl, f"{scalar_name} missing from schema"


def test_datalayer_mutations_exposed():
    sdl = schema.as_str()
    # Every datalayer action must be wired into the Mutation type. Each store
    # type exposes upload (request + finish) and read access; media/zarr/parquet
    # also expose an organization-wide "general" access grant.
    for field in [
        # media
        "requestMediaUpload",
        "finishMediaUpload",
        "requestMediaAccess",
        "requestGeneralMediaAccess",
        # big files
        "requestBigfileUpload",
        "finishBigfileUpload",
        "requestBigfileAccess",
        # zarr
        "requestZarrUpload",
        "finishZarrUpload",
        "requestZarrAccess",
        "requestGeneralZarrAccess",
        # parquet
        "requestParquetUpload",
        "finishParquetUpload",
        "requestParquetAccess",
        "requestGeneralParquetAccess",
    ]:
        assert f"{field}(" in sdl, f"{field} missing from schema"
