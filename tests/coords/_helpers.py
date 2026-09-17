"""Shared helpers for the coordinate-graph tests ported from mikro.

Three things the ported tests need and ``tests/seed.py`` does not give them:

- :func:`derive`, mikro's ``_derive``: a dataset created through ``createArrayDataset`` with a
  ``derivedFrom`` list, over a real store in the compose RustFS.

- :class:`QueryCounter`, mikro's SQL counter for the query-count tests. The schema runs
  async, so the ORM work happens on asgiref's executor thread and ``django_assert_num_queries``
  would instrument the wrong connection.
- :func:`create_experiment` and :func:`add_view`, the stand-in for mikro's ``create_scene`` plus
  ``Layer.objects.create``. mikro's layer names a lens and nothing else; a view here names a
  lens *and* a recording (or stimulus), and a recording needs a simulation. The placement
  resolvers read only the lens and the experiment's world, so the simulation built here is a
  bare holder: it has no clock, and a test that reads ``offset`` or ``duration`` should go
  through ``make_simulation_chain`` + ``createExperiment`` instead.
"""

import threading
import uuid

from asgiref.sync import sync_to_async
from django.db.backends import utils as db_utils
from kante.context import HttpContext

from core import models
from tests import seed


class QueryCounter:
    """Counts every SQL statement, on any thread.

    Not `django_assert_num_queries`: the schema is executed async, so the ORM work
    happens on asgiref's executor thread, whose connection is a different object from
    the one the test thread would instrument. Patching the cursor catches all of them.
    """

    def __init__(self) -> None:
        self.queries: list[str] = []
        self._lock = threading.Lock()

    def __enter__(self) -> "QueryCounter":
        self._execute = db_utils.CursorWrapper.execute
        self._executemany = db_utils.CursorWrapper.executemany

        def execute(inner, sql, params=None):  # noqa: ANN001, ANN202
            with self._lock:
                self.queries.append(sql)
            return self._execute(inner, sql, params)

        def executemany(inner, sql, param_list):  # noqa: ANN001, ANN202
            with self._lock:
                self.queries.append(sql)
            return self._executemany(inner, sql, param_list)

        db_utils.CursorWrapper.execute = execute
        db_utils.CursorWrapper.executemany = executemany
        return self

    def __exit__(self, *exc) -> None:
        db_utils.CursorWrapper.execute = self._execute
        db_utils.CursorWrapper.executemany = self._executemany

    def __len__(self) -> int:
        return len(self.queries)


async def counted(aexecute, query: str, variables: dict | None = None) -> tuple[dict, int]:  # noqa: ANN001 - the conftest fixture
    """The query's data and the number of SQL statements one fresh request costs.

    Warmed once and measured on a second, separate request: the first execution of a
    process pays one-off costs (content types, permissions) that no steady-state client
    pays, and counting them would bury the thing under test. ``aexecute`` builds a fresh
    request per call, so the second does not ride on the first's per-request memos.
    """
    await aexecute(query, variables)
    with QueryCounter() as counter:
        result = await aexecute(query, variables)
    assert not result.errors, result.errors
    return result.data, len(counter)


def _experiment_sync(ctx: HttpContext, name: str, world: models.CoordinateSystem | None, axes: list | None) -> models.Experiment:
    if world is None:
        world = seed._seed_world_sync(ctx, name, axes or seed.ZYX_WORLD_AXES, None)
    return models.Experiment.objects.create(name=name, world=world, creator=ctx.request.user, organization=ctx.request.organization)


async def create_experiment(ctx: HttpContext, name: str = "Experiment", *, world: models.CoordinateSystem | None = None, axes: list | None = None) -> models.Experiment:
    """An experiment over a fresh ownerless world: mikro's ``seed.create_scene``.

    The world defaults to mikro's (z, y, x) in micrometers, because the tests that use this are
    about the graph rather than about what the axes mean. Pass ``axes=seed.CLOCK_AXES`` for a
    timeline, or ``world=`` to adopt an existing space.
    """
    return await sync_to_async(_experiment_sync)(ctx, name, world, axes)


def _holder_simulation(ctx: HttpContext, experiment: models.Experiment) -> models.Simulation:
    """One clockless simulation per experiment, for the recordings its views wrap."""
    name = f"{experiment.name}/holder"
    existing = models.Simulation.objects.filter(name=name, creator=ctx.request.user).first()
    if existing is not None:
        return existing
    environment = models.ModEnvironment.objects.create(name=f"env-{uuid.uuid4().hex}", organization=ctx.request.organization)
    neuron_model = models.NeuronModel.objects.create(name="NeuronModel", hash=uuid.uuid4().hex, json_model={}, creator=ctx.request.user, environment=environment)
    return models.Simulation.objects.create(model=neuron_model, clock=None, name=name, duration=0, creator=ctx.request.user)


def _view_sync(ctx: HttpContext, experiment: models.Experiment, lens: models.Lens, stimulus: bool, label: str | None):  # noqa: ANN202
    simulation = _holder_simulation(ctx, experiment)
    order = experiment.recording_views.count() + experiment.stimulus_views.count()
    if stimulus:
        site = models.Stimulus.objects.create(simulation=simulation, dataset=lens.dataset, kind="CURRENT", cell="soma", location="0", position=0.5)
        return models.ExperimentStimulusView.objects.create(experiment=experiment, stimulus=site, lens=lens, order=order, label=label)
    site = models.Recording.objects.create(simulation=simulation, dataset=lens.dataset, kind="VOLTAGE", cell="soma", location="0", position=0.5)
    return models.ExperimentRecordingView.objects.create(experiment=experiment, recording=site, lens=lens, order=order, label=label)


async def add_view(ctx: HttpContext, experiment: models.Experiment, lens: models.Lens, *, stimulus: bool = False, label: str | None = None):  # noqa: ANN201
    """A view of ``lens`` in ``experiment``: mikro's ``Layer.objects.create(scene=, lens=)``.

    Written through the ORM, so nothing checks that the lens is placeable -- which is what the
    ported tests want, since several of them are about a layer that is *not*.
    """
    return await sync_to_async(_view_sync)(ctx, experiment, lens, stimulus, label)


DERIVE = """
mutation Derive($input: CreateArrayDatasetInput!) {
  createArrayDataset(input: $input) { id name derivedFrom { id kind inputAxes outputAxes valueRelation } }
}
"""


async def derive(aexecute, zarr_store, name: str, *, axes: list, shape: list[int], lens=None, entries: list[dict] | None = None, transform: dict | None = None, value_relation: str | None = None):  # noqa: ANN001, ANN201
    """Create a dataset through the real mutation, stating what it was computed from: mikro's ``_derive``.

    Either one ``lens`` plus its ``transform`` dict (and optional ``value_relation``), or
    explicit ``entries`` for a fusion. mikro's helper patches ``ZarrStore.fill_info`` so that
    no object store is needed; this one does not -- ``zarr_store(shape=...)`` writes a real
    ``zarr.json`` to the compose RustFS, and ``createArrayDataset`` reads it back.
    """
    store = await zarr_store(shape=list(shape), dimension_names=[axis.name for axis in axes])

    if entries is None:
        # IDENTITY stated, not assumed: an omitted `transform` means UNMAPPABLE, and most
        # callers are about a derived dataset that *does* place through its source.
        entry = {"kind": "LENS", "lens": str(lens.pk), "transform": transform if transform is not None else {"kind": "IDENTITY"}}
        if value_relation is not None:
            entry["valueRelation"] = value_relation
        entries = [entry]

    return await aexecute(
        DERIVE,
        {"input": {"data": str(store.pk), "scales": [], "name": name, "axes": [{"name": axis.name, "type": axis.type.value} for axis in axes], "derivedFrom": entries}},
    )


async def derived_dataset(result) -> models.ArrayDataset:  # noqa: ANN001 - an ExecutionResult of `DERIVE`
    """The dataset a successful :func:`derive` made."""
    assert not result.errors, result.errors
    return await models.ArrayDataset.objects.select_related("coordinate_system").aget(pk=result.data["createArrayDataset"]["id"])
