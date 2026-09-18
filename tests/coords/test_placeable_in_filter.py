"""The `placeableIn` filter: which lenses and datasets can be composed into a space.

Ported from mikro's ``tests/test_placeable_in_filter.py``. ``test_coordinate_api.py`` pins the
one-hop case (a dataset sampled onto a clock); this pins what makes the filter trustworthy: that
it agrees with the single-source gate, that it stops at an UNMAPPABLE edge, that it follows a
derivation, and that ``derivedOnly`` narrows without ever adding.

A `Lens` is *placeable in* a coordinate system when a traversable path exists from its own
system into that one -- the very gate ``createExperiment`` applies to a view
(``graph.is_placeable_in``). The filter walks the transformation edges, so it is a Python-side
reachability question, not an ORM join.

It takes a **space**, not an experiment: every experiment over one world offers exactly the
same candidates, so an experiment-shaped argument would ask the caller for more than the
answer depends on. A client holding an experiment passes `experiment.world.id`.

The load-bearing test is the consistency one: the batched helper the filter runs over the
whole candidate set must agree, object for object, with the single-source
``is_placeable_in`` -- otherwise the picker would offer a source that view creation
then refuses (or hide one it would accept).
"""

import pytest
from asgiref.sync import sync_to_async

from core import enums, models
from core.logic import graph as graph_logic
from tests import seed
from tests.coords._helpers import create_experiment

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


LENSES = """
query Lenses($space: ID!, $derivedOnly: Boolean) {
  lenses(filters: { placeableIn: { space: $space, derivedOnly: $derivedOnly } }) { id }
}
"""

DATASETS = """
query Datasets($space: ID!) {
  arrayDatasets(filters: { placeableIn: { space: $space } }) { id }
}
"""


def _derivation(ctx, child: models.ArrayDataset, parent: models.ArrayDataset, kind: str, value_relation: str | None = None) -> models.Transformation:  # noqa: ANN001
    """A derivation edge child -> parent (input = the child's grid, output = the parent's).

    IDENTITY between two c/y/x datasets is a real in-place derivation; UNMAPPABLE records
    "came from that recording" while denying any point correspondence -- the edge the
    placement walk refuses.
    """
    return models.Transformation.objects.create(
        kind=kind,
        input=child.coordinate_system,
        output=parent.coordinate_system,
        organization=ctx.request.organization,
        **({"value_relation": value_relation} if value_relation is not None else {}),
    )


async def _lens_ids(aexecute, space_id, **narrowing) -> set[str]:  # noqa: ANN001
    """The ids the `lenses` picker returns for a space, optionally narrowed."""
    result = await aexecute(LENSES, {"space": str(space_id), **narrowing})
    assert not result.errors, result.errors
    return {lens["id"] for lens in result.data["lenses"]}


async def _dataset_ids(aexecute, space_id) -> set[str]:  # noqa: ANN001
    result = await aexecute(DATASETS, {"space": str(space_id)})
    assert not result.errors, result.errors
    return {dataset["id"] for dataset in result.data["arrayDatasets"]}


def _assert_all_placeable(space: models.CoordinateSystem, lens_ids: set[str]) -> None:
    """Every narrowed candidate is still one view creation would accept.

    The narrowings may only *remove*. A filter that added a candidate `is_placeable_in`
    refuses would be the exact failure this module exists to prevent, arrived at from the
    other direction.
    """
    for lens_id in lens_ids:
        lens = models.Lens.objects.get(pk=lens_id)
        assert graph_logic.is_placeable_in(space, graph_logic.lens_source_system(lens)), f"lens {lens_id} was offered but is not placeable"


async def test_batched_helper_agrees_with_per_candidate_predicate(authenticated_context):
    """The filter's batched set matches ``is_placeable_in`` object for object.

    Unsliced and sliced lenses over a registered and an unregistered dataset -- the one gap
    the whole design fights is the picker and the creating mutation disagreeing about any of them.
    """
    ctx = authenticated_context
    placed = await seed.create_array_dataset(ctx, "Placed")
    unplaced = await seed.create_array_dataset(ctx, "Unplaced")
    world = await seed.create_world(ctx, "Composition", seed.ZYX_WORLD_AXES)
    await seed.register_into_world(ctx, world, placed)

    lenses = [
        await seed.create_lens(ctx, placed),
        await seed.create_lens(ctx, placed, slices=[{"axis": "y", "start": 8, "stop": 40}]),
        await seed.create_lens(ctx, unplaced),
        await seed.create_lens(ctx, unplaced, slices=[{"axis": "x", "start": 4, "stop": 20}]),
    ]

    def check() -> None:
        dataset_ids = graph_logic.placeable_lens_dataset_ids(world)
        for lens in lenses:
            source = graph_logic.lens_source_system(lens)
            expected = graph_logic.is_placeable_in(world, source)
            assert (lens.dataset_id in dataset_ids) == expected, f"lens {lens.pk} disagrees: batched={lens.dataset_id in dataset_ids}, predicate={expected}"
        assert placed.pk in dataset_ids and unplaced.pk not in dataset_ids, "and the agreement is not vacuous: one of each"

    await sync_to_async(check)()


async def test_a_registered_datasets_lenses_are_placeable(aexecute, authenticated_context):
    """Every lens of a registered dataset -- even a fresh, never-viewed one -- is offered; none of an unregistered dataset's are."""
    ctx = authenticated_context
    placed = await seed.create_array_dataset(ctx, "Placed")
    unplaced = await seed.create_array_dataset(ctx, "Unplaced")
    world = await seed.create_world(ctx, "Composition", seed.ZYX_WORLD_AXES)
    await seed.register_into_world(ctx, world, placed)

    fresh = await seed.create_lens(ctx, placed)
    sliced = await seed.create_lens(ctx, placed, slices=[{"axis": "y", "start": 8, "stop": 40}])
    orphan = await seed.create_lens(ctx, unplaced)

    ids = await sync_to_async(graph_logic.placeable_lens_dataset_ids)(world)
    assert placed.pk in ids
    assert unplaced.pk not in ids

    returned = await _lens_ids(aexecute, world.pk)
    assert str(fresh.pk) in returned
    assert str(sliced.pk) in returned
    assert str(orphan.pk) not in returned


async def test_unmappable_is_excluded_but_a_mappable_descendant_is_placeable(authenticated_context):
    """A mappable derived dataset rides its parent's registration to world; an UNMAPPABLE one does not.

    Registering only the root, a lens of the IDENTITY-derived child is placeable (the
    descendant closure), while a lens of the UNMAPPABLE-derived child is not (the gate).
    """
    ctx = authenticated_context
    root = await seed.create_array_dataset(ctx, "Root")
    mappable = await seed.create_array_dataset(ctx, "MappableChild")
    unmappable = await seed.create_array_dataset(ctx, "UnmappableChild")
    world = await seed.create_world(ctx, "Composition", seed.ZYX_WORLD_AXES)
    await seed.register_into_world(ctx, world, root)

    def wire() -> None:
        _derivation(ctx, mappable, root, enums.TransformKindChoices.IDENTITY.value)
        _derivation(ctx, unmappable, root, enums.TransformKindChoices.UNMAPPABLE.value)

    await sync_to_async(wire)()

    lens_mappable = await seed.create_lens(ctx, mappable)
    lens_unmappable = await seed.create_lens(ctx, unmappable)

    def check() -> None:
        ids = graph_logic.placeable_lens_dataset_ids(world)
        assert root.pk in ids
        assert mappable.pk in ids, "a mappable descendant is placed through its parent's registration"
        assert unmappable.pk not in ids, "the UNMAPPABLE gate refuses a derivation whose geometry did not survive"
        # Consistency with the single-source predicate, again, on the derived sources.
        for lens, dataset_id in ((lens_mappable, mappable.pk), (lens_unmappable, unmappable.pk)):
            source = graph_logic.lens_source_system(lens)
            assert (dataset_id in ids) == graph_logic.is_placeable_in(world, source)

    await sync_to_async(check)()


async def test_two_scenes_over_one_world_share_the_placeable_set(aexecute, authenticated_context):
    """One truth per space: the placeable set is the world's, so every experiment over it agrees.

    The registration is a fact about the space, not a per-experiment endorsement -- there is
    no membership for it to leak through or be gated by.
    """
    ctx = authenticated_context
    dataset = await seed.create_array_dataset(ctx, "Shared")
    experiment_a = await create_experiment(ctx, "ExperimentA")
    world = await sync_to_async(lambda: experiment_a.world)()
    experiment_b = await create_experiment(ctx, "ExperimentB", world=world)
    await seed.register_into_world(ctx, world, dataset)

    def check() -> None:
        assert dataset.pk in graph_logic.placeable_lens_dataset_ids(experiment_a.world)
        assert dataset.pk in graph_logic.placeable_lens_dataset_ids(experiment_b.world), "candidates are a property of the space, identical for every experiment over it"

    await sync_to_async(check)()


async def test_array_dataset_placeable_in_agrees_with_its_lenses(aexecute, authenticated_context):
    """A dataset is offered exactly when one of its lenses is: same set, one hop up.

    Both read `placeable_lens_dataset_ids`, so the picker cannot offer a dataset whose
    every lens the creating mutation would refuse, nor hide one it would accept.
    """
    ctx = authenticated_context
    placed = await seed.create_array_dataset(ctx, "Placed")
    unplaced = await seed.create_array_dataset(ctx, "Unplaced")
    world = await seed.create_world(ctx, "Composition", seed.ZYX_WORLD_AXES)
    await seed.register_into_world(ctx, world, placed)
    await seed.create_lens(ctx, placed)
    await seed.create_lens(ctx, unplaced)

    datasets = await _dataset_ids(aexecute, world.pk)
    assert datasets == {str(placed.pk)}

    lens_ids = await _lens_ids(aexecute, world.pk)
    lens_datasets = {str(dataset_id) async for dataset_id in models.Lens.objects.filter(pk__in=lens_ids).values_list("dataset_id", flat=True)}
    assert lens_datasets == datasets


async def test_a_derived_dataset_is_placeable_through_its_source(aexecute, authenticated_context):
    """The descendant closure reaches datasets too: a child is offered on its parent's registration.

    And an UNMAPPABLE derivation is where that stops -- the walk refuses the edge, so the
    child is not offered however much it owes the source historically.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Source")
    derived = await seed.create_array_dataset(ctx, "Derived")
    severed = await seed.create_array_dataset(ctx, "Severed")
    world = await seed.create_world(ctx, "Composition", seed.ZYX_WORLD_AXES)
    await seed.register_into_world(ctx, world, source)
    await sync_to_async(_derivation)(ctx, derived, source, enums.TransformKindChoices.IDENTITY.value)
    await sync_to_async(_derivation)(ctx, severed, source, enums.TransformKindChoices.UNMAPPABLE.value)
    for dataset in (source, derived, severed):
        await seed.create_lens(ctx, dataset)

    assert await _dataset_ids(aexecute, world.pk) == {str(source.pk), str(derived.pk)}


async def test_derived_only_keeps_the_segmentation_and_drops_the_registered_image(aexecute, authenticated_context):
    """`derivedOnly` is the descendant closure without its seeds: what rode a parent's registration here."""
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Source")
    derived = await seed.create_array_dataset(ctx, "Derived")
    world = await seed.create_world(ctx, "Composition", seed.ZYX_WORLD_AXES)
    await seed.register_into_world(ctx, world, source)
    await sync_to_async(_derivation)(ctx, derived, source, enums.TransformKindChoices.IDENTITY.value)

    source_lens = await seed.create_lens(ctx, source)
    derived_lens = await seed.create_lens(ctx, derived)

    assert await _lens_ids(aexecute, world.pk) == {str(source_lens.pk), str(derived_lens.pk)}
    narrowed = await _lens_ids(aexecute, world.pk, derivedOnly=True)
    assert narrowed == {str(derived_lens.pk)}, "the registered recording needs no lineage tree, so it is not what `derivedOnly` asks for"

    await sync_to_async(_assert_all_placeable)(world, narrowed)


async def test_derived_only_drops_a_dataset_that_is_registered_as_well_as_derived(aexecute, authenticated_context):
    """Registered *and* derived is still registered: it does not need its lineage to be placeable.

    The rule is "needed a lineage tree to get here", not "has a lineage". `_derivation_descendants`
    already enforces it by seeding `seen` with the registered containers, which is why there is
    no set subtraction to get wrong.
    """
    ctx = authenticated_context
    source = await seed.create_array_dataset(ctx, "Source")
    both = await seed.create_array_dataset(ctx, "RegisteredAndDerived")
    world = await seed.create_world(ctx, "Composition", seed.ZYX_WORLD_AXES)
    await seed.register_into_world(ctx, world, source)
    await seed.register_into_world(ctx, world, both)
    await sync_to_async(_derivation)(ctx, both, source, enums.TransformKindChoices.IDENTITY.value)

    source_lens = await seed.create_lens(ctx, source)
    both_lens = await seed.create_lens(ctx, both)

    assert await _lens_ids(aexecute, world.pk) == {str(source_lens.pk), str(both_lens.pk)}
    assert await _lens_ids(aexecute, world.pk, derivedOnly=True) == set()
