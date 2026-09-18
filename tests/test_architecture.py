"""Invariants of the code base that no behavioural test would notice being broken.

The first is ported from mikro's ``tests/test_architecture.py``; the container and
composition tests are the same idea, extended to the one registry this service adds.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_the_models_and_the_migrations_agree() -> None:
    """A model edited without its migration is invisible to the rest of this suite.

    ``elektro_server.settings_test`` sets ``MIGRATION_MODULES = DisableMigrations()``, so the
    test database is built straight from the models and **no migration is ever executed
    here**. That makes model/migration drift completely undetectable by every other test: you
    can add a field, forget the migration, and stay green all the way to a deploy that fails on
    ``migrate``. So this one runs the check against the real settings, in a subprocess,
    because the drift it looks for is one the test settings are designed not to see.
    """
    result = subprocess.run(
        [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
        cwd=REPO,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "elektro_server.settings"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"models have changes with no migration:\n{result.stdout}\n{result.stderr}"


def _links_to_coordinate_systems() -> list[tuple[str, str, str]]:
    """Every ``(model, field, reverse accessor)`` by which a core model points at a coordinate system."""
    from django.apps import apps

    from core.models import CoordinateSystem

    return [
        (model.__name__, field.name, field.remote_field.related_name or "")
        for model in apps.get_app_config("core").get_models()
        # The historical twins carry the same FKs and are rows about rows.
        if not model.__name__.startswith("Historical")
        for field in model._meta.get_fields()
        if field.is_relation and field.many_to_one and field.related_model is CoordinateSystem
    ]


def test_every_link_to_a_coordinate_system_is_accounted_for() -> None:
    """Data lives in a space, a composition is laid out over one, and the graph is made of them: nothing else may point at one.

    A model with a ``coordinate_system`` FK is, by definition, somewhere data lives. Missing
    from ``CONTAINERS`` its space reads two ways at once -- inhabited to everything that follows
    the FK, an *uninhabited reference frame* to ``_UNINHABITED``, which is derived from the
    registry -- and it drops out of ``CoordinateSystem.residents`` silently. A model laid out
    *over* a space (a block on its clock, an experiment over its world) missing from
    ``WORLD_RELATIONS`` is worse: the orphan sweep and ``sweep_empty_systems`` both take
    "nothing lives here and nothing is laid out here" as licence to delete, so its clock would
    be swept out from under it. Deriving the expectation from the FKs is what makes the next
    such model a failing test rather than a deleted clock.
    """
    from core.logic.graph import CONTAINERS, WORLD_RELATIONS

    # The graph's own structure: an axis is a component of a system, and an edge has endpoints
    # and (for a lookup) a field. They are on the other side of the relationship.
    # Likewise the frame a collection's stored bounding boxes are denominated in: it *names* a
    # space, it neither lives in it nor is laid out over it (and `sweep_empty_systems` has its
    # own guard for it, because the FK is PROTECT).
    structural = {("Axis", "coordinate_system"), ("Transformation", "input"), ("Transformation", "output"), ("Transformation", "field"), ("AnnotationCollection", "bbox_system")}
    residents = {(container.model.__name__, "coordinate_system") for container in CONTAINERS}

    unaccounted = []
    for model, field, related_name in _links_to_coordinate_systems():
        if (model, field) in structural or (model, field) in residents:
            continue
        if related_name in WORLD_RELATIONS:
            continue
        unaccounted.append(f"{model}.{field} (reverse accessor '{related_name}')")

    assert not unaccounted, (
        f"{', '.join(unaccounted)} point at a coordinate system but are neither in `CONTAINERS` (data living in it) nor in `WORLD_RELATIONS` (something laid out over it). "
        "An unregistered resident vanishes from `residents`; an unregistered composition has its space swept out from under it."
    )

    # And the converse: the registries name nothing that does not exist.
    accessors = {related_name for _, _, related_name in _links_to_coordinate_systems()}
    assert set(WORLD_RELATIONS) <= accessors, f"`WORLD_RELATIONS` names reverse accessors no model defines: {sorted(set(WORLD_RELATIONS) - accessors)}"
    assert {container.related_name for container in CONTAINERS} <= accessors


def test_every_registered_container_is_a_member_of_the_resident_union() -> None:
    """A container the union does not name is a resident nothing can return.

    Checked against the SDL rather than the Python union, so that a member which is declared but
    never registered in the schema is caught too.
    """
    from core.logic.graph import CONTAINERS
    from elektro_server.schema import schema

    match = re.search(r"union Resident = ([^\n]+)", schema.as_str())
    assert match, "the SDL declares no `Resident` union at all"
    members = {name.strip() for name in match.group(1).split("|")}

    missing = sorted(container.model.__name__ for container in CONTAINERS if container.model.__name__ not in members)
    assert not missing, f"{', '.join(missing)} are containers but not members of `Resident`: {sorted(members)}"


def test_every_vertex_count_rule_names_an_annotation_kind() -> None:
    """A kind renamed in the enum must not leave its vertex rule behind under the old name.

    mikro's table once carried six keys from the ROI vocabulary that had stopped backing
    ``Annotation.kind``: no annotation could be drawn as one, so no lookup could reach them, and
    nothing said so.
    """
    from core import enums
    from core.inputs.validators import _MINIMUM_VERTICES

    kinds = {choice.value for choice in enums.AnnotationKindChoices}
    assert set(_MINIMUM_VERTICES) <= kinds, f"vertex rules for kinds that do not exist: {sorted(set(_MINIMUM_VERTICES) - kinds)}"
    assert {kind.value for kind in enums.AnnotationKind} == kinds, "the GraphQL enum and its database twin must list the same kinds"


def test_the_vendored_graph_names_no_model_this_service_does_not_have() -> None:
    """The coordinate modules are vendored from mikro; a symbol that only exists there is a latent AttributeError.

    Prose may say "dataset" -- it was left as mikro wrote it, on purpose -- but code may not say
    ``models.ArrayDataset``. Every ``models.<Name>`` in the vendored modules must resolve.
    """
    from core import models

    vendored = [
        "core/logic/coords.py", "core/logic/graph.py", "core/logic/edge_universe.py", "core/logic/space_graph.py", "core/logic/scene_graph.py",
        "core/logic/coordinate_system.py", "core/inputs/coords.py", "core/types/coords.py", "core/mutations/coordinate_system.py", "core/mutations/transformation.py",
        "core/mutations/annotation.py", "core/mutations/annotation_collection.py", "core/queries/annotations.py",
        "core/logic/identification.py", "core/logic/tables.py", "core/logic/pickers.py", "core/inputs/identification.py", "core/inputs/sparse.py",
        "core/mutations/sparse_dataset.py", "core/mutations/table_dataset.py", "core/types/sparse_dataset.py", "core/types/table_dataset.py",
    ]  # fmt: skip
    dangling = []
    for relative in vendored:
        source = (REPO / relative).read_text()
        # Drop comments, docstrings and string annotations: only names the interpreter evaluates matter.
        code = re.sub(r'""".*?"""', "", source, flags=re.S)
        code = re.sub(r"#.*", "", code)
        code = re.sub(r'"[^"\n]*"', '""', code)
        for name in sorted(set(re.findall(r"\bmodels\.([A-Z][A-Za-z]+)\b", code))):
            if not hasattr(models, name):
                dangling.append(f"{relative}: models.{name}")
    assert not dangling, f"vendored code names models this service does not have: {dangling}"


_MIGRATE_IN_A_SCRATCH_DATABASE = '''
import django
from django.conf import settings
from elektro_server import settings_test  # noqa: F401 - the test stack's connection parameters

settings.MIGRATION_MODULES = {}                      # the one thing the test settings switch off
settings.DATABASES["default"]["NAME"] = "migrate_check"
django.setup()

from django.core.management import call_command
from django.db import connection

call_command("migrate", interactive=False, verbosity=0)
tables = set(connection.introspection.table_names())
for table in (
    "core_coordinatesystem", "core_axis", "core_transformation", "core_lens", "core_historicaltransformation", "core_filelink", "core_annotation", "core_annotationcollection",
    "core_tabledataset", "core_column", "core_sparsedataset", "core_sparsearray", "core_sparseaxisreference", "core_experimentlayer", "core_recordingsite", "core_stimulussite",
    "datalayer_sparsestore",
):  # fmt: skip
    assert table in tables, f"{table} was not created by the migrations"
print("migrated", len(tables), "tables")
'''


def test_the_migrations_actually_run(backend_stack) -> None:  # noqa: ANN001 - the dokker stack fixture
    """``makemigrations --check`` proves the migration matches the models; this proves it *executes*.

    On a real Postgres, from nothing, the way a fresh deployment's ``manage.py migrate`` does.
    Every other test builds its tables straight from the models, so an initial migration that
    cannot run -- a field that needs an extension, a dependency ordered wrong, a constraint
    Postgres rejects -- would otherwise first be found by the container failing to boot.
    """
    import psycopg

    with psycopg.connect(dbname="testdb", user="test", password="test", host="localhost", port=5555, autocommit=True) as connection:
        connection.execute("DROP DATABASE IF EXISTS migrate_check")
        connection.execute("CREATE DATABASE migrate_check")
    try:
        result = subprocess.run(
            [sys.executable, "-c", _MIGRATE_IN_A_SCRATCH_DATABASE],
            cwd=REPO,
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "elektro_server.settings_test"},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"`migrate` failed on an empty database:\n{result.stdout[-2000:]}\n{result.stderr[-4000:]}"
        assert "migrated" in result.stdout
    finally:
        with psycopg.connect(dbname="testdb", user="test", password="test", host="localhost", port=5555, autocommit=True) as connection:
            connection.execute("DROP DATABASE IF EXISTS migrate_check WITH (FORCE)")


def test_every_picker_column_is_guarded() -> None:
    """The delete guards cover every JSON column a picker is stored in.

    Ported from mikro. A picker entry names its table (or matrix) by id inside JSON, so nothing
    cascades: a table deleted out from under a picker strands the entry as a join nothing can
    execute, surfacing at render time. `core.logic.pickers` refuses such a delete, but only for
    the columns it lists -- so the list is derived from the model here, and the next layer
    kind's picker fails this the moment it exists.
    """
    from django.db import models as django_models

    from core import models
    from core.logic.pickers import _PICKER_COLUMNS

    stored = sorted(
        field.name
        for field in models.ExperimentLayer._meta.get_fields()
        if isinstance(field, django_models.JSONField) and (field.name.endswith("_color_bys") or field.name.endswith("_filter_bys"))
        # `active_filter_bys` shares the suffix but stores indices into a picker, not entries.
        and field.name != "active_filter_bys"
    )
    assert stored == sorted(_PICKER_COLUMNS), f"picker columns the delete guards do not look in: {sorted(set(stored) - set(_PICKER_COLUMNS))}"


def test_the_layer_kinds_and_their_sources_agree() -> None:
    """One source FK per kind, in the model's constraint, the builder's table and the placement dispatch alike."""
    from core import enums
    from core.logic import experiment as experiment_logic

    kinds = {choice.value for choice in enums.ExperimentLayerKindChoices}
    assert set(experiment_logic.SOURCE_FIELD) == kinds
    assert {kind.value for kind in enums.ExperimentLayerKind} == kinds, "the GraphQL enum and its database twin list the same kinds"
    from elektro_server.schema import schema

    sdl = str(schema)
    for concrete in ("TraceLayer", "SpikesLayer", "EventsLayer", "AnnotationLayer"):
        assert f"type {concrete} implements ExperimentLayer" in sdl, f"{concrete} is not registered in the schema's `types=`"
