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
