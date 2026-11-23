"""Sharing a workflow: what a root task created in elektro, put in a collaboration as it is now.

A workflow is a root task (koherent's ``Task.root_task_id``). What it made here koherent reads off each
model: the ``created_through`` task of a dataset, the CREATE row of a lens' or an experiment's
history. A test stamps both where a request under a provenance token would (``_made_in``), the way
the delete-guard tests do: a ``koherent.Task`` row of the organization, and the creation pointing at it.

The collaboration is lok's, named by a key: a full member shares under a fresh one, and a guest's
token names the same key.
"""

import uuid
from dataclasses import dataclass

import pytest
from arkitekt_service.collaborations.models import Collaboration, CollaborationItem
from asgiref.sync import sync_to_async
from django.db.models import Model
from kante.context import HttpContext, Organization
from koherent.models import Task
from strawberry.types import ExecutionResult

from core import models
from elektro_server.schema import schema
from tests import seed
from tests.conftest import token_context
from tests.fixture_types import GraphQLData, GuestFactory

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

SHARE = """
mutation ($input: ShareWorkflowInput!) {
  shareWorkflow(input: $input) {
    collaboration
    dryRun
    added { identifier object }
    covered
    skipped { identifier object wholeIdentifier whole }
    unknown
  }
}
"""
ADD = "mutation ($input: CollaborationObjectInput!) { addToCollaboration(input: $input) { key } }"
CREATE_EXPERIMENT = "mutation ($input: CreateExperimentInput!) { createExperiment(input: $input) { id } }"
LISTS = """
query ($experiments: ExperimentFilter, $datasets: ArrayDatasetFilter, $lenses: LensFilter, $collections: ModelCollectionFilter) {
  experiments(filters: $experiments) { id }
  arrayDatasets(filters: $datasets) { id }
  lenses(filters: $lenses) { id }
  modelCollections(filters: $collections) { id }
}
"""


async def _run(ctx: HttpContext, query: str, **variables: object) -> ExecutionResult:
    return await schema.execute(
        query, context_value=ctx, variable_values=variables or None
    )


async def _member(query: str, **variables: object) -> GraphQLData:
    """Run ``query`` as the full member, as a request of its own, and hand back its data."""
    result = await _run(token_context("test"), query, **variables)
    assert not result.errors, result.errors
    assert result.data is not None
    return result.data


def _task(organization: Organization, root: str) -> Task:
    """One task of the workflow ``root``, as a verified provenance token leaves it behind."""
    token = uuid.uuid4().hex
    return Task.objects.create(
        task_id=f"task-{token}",
        root_task_id=root,
        assigner_sub="1",
        caller_sub="1",
        agent_sub="agent",
        agent_client_id="agent-client",
        issuer="static_issuer",
        token_id=f"tok-{token}",
        args_hash="",
        args_hash_algorithm="",
        organization=organization,
    )


def _made_in(task: Task, *objects: Model) -> None:
    """Say that ``objects`` were created under ``task``: their ``created_through``, and the CREATE row
    of their history, where the model keeps one."""
    for obj in objects:
        model = type(obj)
        fields = {f.name for f in model._meta.get_fields()}
        if "created_through" in fields:
            model._base_manager.filter(pk=obj.pk).update(created_through=task)
        if "provenance_entries" in fields:
            history = model._meta.get_field("provenance_entries").related_model
            assert history is not None and not isinstance(history, str)
            assert (
                history._base_manager.filter(
                    **{model._meta.pk.attname: obj.pk}, history_type="+"
                ).update(task=task)
                == 1
            )


@dataclass(frozen=True)
class Workflow:
    """A workflow's root task and what it touched, beside what it did not."""

    root: str
    experiment: models.Experiment
    dataset: models.ArrayDataset
    lens: models.Lens
    #: Made before the workflow, and not shared; the workflow only cut a lens over it.
    older: models.ArrayDataset
    lens_over_older: models.Lens
    #: Made in the organization, but not by the workflow.
    unrelated: models.Experiment


async def _workflow(ctx: HttpContext) -> Workflow:
    """A workflow (two tasks under one root) that made an experiment, a dataset with a lens over
    it, and a lens over an older dataset; plus what it did not make."""
    older = await seed.create_dataset(ctx, "Older")
    unrelated = await models.Experiment.objects.aget(
        pk=(await _member(CREATE_EXPERIMENT, input={"name": "Unrelated"}))[
            "createExperiment"
        ]["id"]
    )
    experiment = await models.Experiment.objects.aget(
        pk=(await _member(CREATE_EXPERIMENT, input={"name": "Made"}))[
            "createExperiment"
        ]["id"]
    )
    dataset = await seed.create_dataset(ctx, "Made")
    lens = await seed.create_lens(ctx, dataset)
    lens_over_older = await seed.create_lens(ctx, older)
    await models.ModelCollection.objects.acreate(
        name="Says nothing of its workflow",
        organization=ctx.request.organization,
        creator=ctx.request.user,
    )
    root = f"root-{uuid.uuid4().hex}"

    def stamp() -> None:
        first, second = (
            _task(ctx.request.organization, root),
            _task(ctx.request.organization, root),
        )
        _made_in(first, experiment, dataset)
        _made_in(second, lens, lens_over_older)

    await sync_to_async(stamp)()
    return Workflow(
        root=root,
        experiment=experiment,
        dataset=dataset,
        lens=lens,
        older=older,
        lens_over_older=lens_over_older,
        unrelated=unrelated,
    )


def _ids(data: GraphQLData, field: str) -> set[str]:
    return {row["id"] for row in data[field]}


def _report(workflow: Workflow, key: str, *, dry_run: bool) -> GraphQLData:
    """What sharing ``workflow`` reports: its experiment and dataset put in, its lens covered by
    its dataset, the lens over the older dataset left out, the model collections unknown."""
    return {
        "collaboration": key,
        "dryRun": dry_run,
        "added": [
            {"identifier": "@elektro/arraydataset", "object": str(workflow.dataset.pk)},
            {
                "identifier": "@elektro/experiment",
                "object": str(workflow.experiment.pk),
            },
        ],
        "covered": 1,
        "skipped": [
            {
                "identifier": "@elektro/lens",
                "object": str(workflow.lens_over_older.pk),
                "wholeIdentifier": "@elektro/arraydataset",
                "whole": str(workflow.older.pk),
            }
        ],
        "unknown": ["@elektro/modelcollection"],
    }


def _sorted(share: GraphQLData) -> GraphQLData:
    return {
        **share,
        "added": sorted(share["added"], key=lambda a: (a["identifier"], a["object"])),
    }


async def test_a_dry_run_says_what_sharing_a_workflow_puts_in_and_writes_nothing(
    authenticated_context: HttpContext,
) -> None:
    workflow = await _workflow(authenticated_context)
    key = str(uuid.uuid4())

    tried = await _member(
        SHARE, input={"collaboration": key, "rootTask": workflow.root, "dryRun": True}
    )

    assert _sorted(tried["shareWorkflow"]) == _report(workflow, key, dry_run=True)
    assert not await Collaboration.objects.filter(key=key).aexists(), (
        "a dry run makes no row of the collaboration here"
    )
    assert await CollaborationItem.objects.acount() == 0


async def test_sharing_a_workflow_puts_in_what_it_made_and_a_guest_sees_exactly_that(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    workflow = await _workflow(authenticated_context)
    key = str(uuid.uuid4())
    ctx = guest({key: []})
    before = await _run(ctx, LISTS)
    assert not before.errors, before.errors
    assert before.data == {
        "experiments": [],
        "arrayDatasets": [],
        "lenses": [],
        "modelCollections": [],
    }, "a key granted before anything is put in here holds nothing"

    shared = await _member(
        SHARE,
        input={"collaboration": key, "rootTask": workflow.root, "name": "Pilot"},
    )

    assert _sorted(shared["shareWorkflow"]) == _report(workflow, key, dry_run=False)
    collaboration = await Collaboration.objects.aget(key=key)
    assert collaboration.name == "Pilot"
    seen = await _run(guest({key: []}), LISTS)
    assert not seen.errors, seen.errors
    assert seen.data is not None
    assert _ids(seen.data, "experiments") == {str(workflow.experiment.pk)}
    assert _ids(seen.data, "arrayDatasets") == {str(workflow.dataset.pk)}
    assert _ids(seen.data, "lenses") == {str(workflow.lens.pk)}, (
        "the lens with its dataset, and not the one over the older dataset"
    )
    assert seen.data["modelCollections"] == []

    stranger = await _run(guest({str(uuid.uuid4()): []}), LISTS)
    assert not stranger.errors, stranger.errors
    assert stranger.data is not None
    assert all(rows == [] for rows in stranger.data.values()), (
        "another key sees nothing of it"
    )


async def test_a_lens_over_an_older_dataset_comes_along_once_that_dataset_is_shared(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    workflow = await _workflow(authenticated_context)
    key = str(uuid.uuid4())
    await _member(SHARE, input={"collaboration": key, "rootTask": workflow.root})
    assert str(workflow.lens_over_older.pk) not in _ids(
        (await _run(guest({key: []}), LISTS)).data or {}, "lenses"
    ), "the workflow does not hand out a part of what it did not make"

    await _member(
        ADD,
        input={
            "collaboration": key,
            "identifier": "@elektro/arraydataset",
            "object": str(workflow.older.pk),
        },
    )
    again = await _member(
        SHARE, input={"collaboration": key, "rootTask": workflow.root}
    )

    assert again["shareWorkflow"]["skipped"] == []
    assert again["shareWorkflow"]["covered"] == 2, "both lenses, with their datasets"
    seen = await _run(guest({key: []}), LISTS)
    assert seen.data is not None
    assert _ids(seen.data, "lenses") == {
        str(workflow.lens.pk),
        str(workflow.lens_over_older.pk),
    }


async def test_lists_filter_by_the_workflow_that_made_them_and_by_collaboration(
    authenticated_context: HttpContext,
) -> None:
    workflow = await _workflow(authenticated_context)
    key = str(uuid.uuid4())
    under = {"createdUnder": workflow.root}

    made = await _member(
        LISTS, experiments=under, datasets=under, lenses=under, collections=under
    )

    assert _ids(made, "experiments") == {str(workflow.experiment.pk)}
    assert _ids(made, "arrayDatasets") == {str(workflow.dataset.pk)}
    assert _ids(made, "lenses") == {
        str(workflow.lens.pk),
        str(workflow.lens_over_older.pk),
    }
    assert made["modelCollections"] == [], "a model collection cannot say"

    inside = {"inCollaboration": key}
    nothing_yet = await _member(
        LISTS, experiments=inside, datasets=inside, lenses=inside
    )
    assert all(nothing_yet[f] == [] for f in ("experiments", "arrayDatasets", "lenses"))

    await _member(SHARE, input={"collaboration": key, "rootTask": workflow.root})
    shared = await _member(LISTS, experiments=inside, datasets=inside, lenses=inside)

    assert _ids(shared, "experiments") == {str(workflow.experiment.pk)}
    assert _ids(shared, "arrayDatasets") == {str(workflow.dataset.pk)}
    assert _ids(shared, "lenses") == {str(workflow.lens.pk)}, (
        "a part of what was put in is in it, live"
    )
    both = await _member(
        LISTS,
        experiments={"createdUnder": workflow.root, "inCollaboration": key},
        datasets={"inCollaboration": key, "ids": [str(workflow.older.pk)]},
    )
    assert _ids(both, "experiments") == {str(workflow.experiment.pk)}
    assert both["arrayDatasets"] == []


async def test_another_organization_shares_nothing_of_this_workflow(
    authenticated_context: HttpContext,
) -> None:
    workflow = await _workflow(authenticated_context)

    tried = await _run(
        token_context("othertest"),
        SHARE,
        input={
            "collaboration": str(uuid.uuid4()),
            "rootTask": workflow.root,
            "dryRun": True,
        },
    )

    assert not tried.errors, tried.errors
    assert tried.data is not None
    assert tried.data["shareWorkflow"]["added"] == []
    assert tried.data["shareWorkflow"]["skipped"] == []


async def test_an_explicit_null_filters_nothing(
    authenticated_context: HttpContext,
) -> None:
    workflow = await _workflow(authenticated_context)
    unset = {"inCollaboration": None, "createdUnder": None}

    listed = await _member(LISTS, experiments=unset, datasets=unset)

    assert _ids(listed, "experiments") == {
        str(workflow.experiment.pk),
        str(workflow.unrelated.pk),
    }
    assert _ids(listed, "arrayDatasets") == {
        str(workflow.dataset.pk),
        str(workflow.older.pk),
    }
