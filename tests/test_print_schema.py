"""Smoke test: the GraphQL schema must build and render to a non-empty SDL string.

No database required — this only imports and stringifies the schema.
"""

from elektro_server.schema import schema


def test_print_schema():
    sdl = str(schema)
    print(sdl)  # visible with `pytest -s`
    assert sdl.strip(), "Schema SDL should not be empty"


def test_provenance_filter_fields_exposed():
    """The flat provenance/creator filters must reach the SDL.

    These lookups only fail at query time (a FieldError on a bad relation path),
    so a build-time assertion is the cheapest guard that the mixins stay wired
    into SimulationFilter/ExperimentFilter.
    """
    sdl = str(schema)
    for field in [
        "createdBy",
        "mine",
        "provenanceTask",
        "provenanceRootTask",
        "createdWith",
        "createdByAgent",
    ]:
        assert field in sdl, f"expected filter field {field!r} in SDL"


#: mikro's field sets for the vendored table and sparse types, as mikro's SDL printed them when
#: they were vendored (2026-09-18). The data layer is mikro's by name, so a client written against
#: mikro's tables and matrices works here: what elektro may differ by is exactly `_DIVERGENCES`.
#:
#: A *snapshot*, because this test cannot import mikro: if mikro grows a field, this still passes.
#: Refresh it whenever these types are re-vendored -- print mikro's SDL from its own checkout
#: (`DJANGO_SETTINGS_MODULE=mikro_server.settings python -c "import django; django.setup();
#: from mikro_server.schema import schema; print(schema.as_str())"`), read each type's field
#: names off it with `graphql.build_schema(sdl, assume_valid_sdl=True).type_map[name].fields`,
#: and paste them here. Any difference beyond `_DIVERGENCES` is a vendoring bug.
_MIKRO_FIELDS = {
    "Column": ["axisType", "description", "dtype", "id", "longName", "name", "nodeReferences", "order", "references", "role", "table", "unit"],
    "ColumnInput": ["axisType", "description", "dtype", "identifiedBy", "longName", "name", "role", "unit"],
    "CreateSparseDatasetInput": ["axes", "derivedFrom", "description", "folder", "name", "sourceFiles", "store"],
    "CreateTableDatasetInput": ["columns", "data", "derivedFrom", "description", "folder", "name", "sourceFiles"],
    "IdentificationInput": ["dataset", "kind", "meshCollection", "name", "networkCollection", "table", "validity"],
    "SparseArray": ["id", "indexedAxis", "indexedAxisName", "path", "store"],
    "SparseAxisInput": ["description", "identifiedBy", "longName", "name"],
    "SparseAxisReference": ["axis", "id", "references"],
    "SparseDataset": ["arrays", "axisNames", "axisReferences", "coordinateSystem", "createdThrough", "createdThroughBy", "derivedFrom", "description", "folder", "id", "indexableAxes", "name", "provenanceEntries", "provenanceMetadata", "shape", "sourceFiles"],
    "SparseLayout": ["chunks", "dtype", "encoding", "encodingVersion", "indexOrder", "indexedAxis", "nnz", "path", "rangeReadable"],
    "TableDataset": ["axisNames", "columns", "coordinateSystem", "createdThrough", "createdThroughBy", "derivedFrom", "description", "exports", "folder", "id", "name", "provenanceEntries", "provenanceMetadata", "referencedBy", "sourceFiles", "store"],
}

#: Every place the vendored types differ from mikro's, and why -- `core/DESIGN.md` lists the same.
_DIVERGENCES = {
    # elektro has no network collections, so there is no node id for a column to reference.
    "Column": ({"nodeReferences"}, set()),
    # ... nor mesh or network collections for an axis to be identified by.
    "IdentificationInput": ({"meshCollection", "networkCollection"}, set()),
    # A spike raster's sample axis is TIME: the one additive field of the port.
    "SparseAxisInput": (set(), {"type"}),
}


def test_the_vendored_table_and_sparse_types_are_mikros():
    from graphql import build_schema

    built = build_schema(str(schema), assume_valid_sdl=True)
    for name, fields in _MIKRO_FIELDS.items():
        removed, added = _DIVERGENCES.get(name, (set(), set()))
        expected = (set(fields) - removed) | added
        assert set(built.type_map[name].fields) == expected, f"{name} drifted from mikro's beyond the recorded divergences"

    kinds = set(built.type_map["IdentificationKind"].values)
    assert kinds == {"DATASET", "TABLE"}, "mikro's MESH_COLLECTION / NETWORK_COLLECTION / NETWORK_COLLECTION_NODES have nothing to name here"
