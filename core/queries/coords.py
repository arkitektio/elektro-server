"""Queries over the coordinate graph itself, rather than over one of its nodes.

Vendored from mikro's ``core/queries/coords.py`` (attribute plans, a table concept, are cut). Read "dataset" as "dataset" and "scene" as "experiment".
"""

import strawberry
from kante.types import Info

from core import models, types
from core.logic import graph as graph_logic
from core.scoping import get_for_org


def coordinate_graph(
    info: Info,
    coordinate_system: strawberry.ID,
    max_depth: int | None = None,
) -> types.CoordinateGraph:
    """Walk the coordinate graph out from one system and return the subgraph it reaches.

    The list queries answer "which edges are there"; this answers "which edges relate to
    *this*", which no filter can, because relatedness is transitive and a filter is not. It
    is the one traversal that is not scene-scoped: `Layer.pathToWorld` answers where a layer
    sits in the scene it belongs to, whereas this hands back the neighbourhood -- a dataset's
    pixel grid, its pyramid levels, its lenses, its physical spaces, the worlds it is registered
    into, and anything else registered into those.

    It still composes nothing. The subgraph comes back as nodes and directed edges, and
    turning that into a matrix is the client's job, for the same reason it always is: two
    scenes can place the same dataset two different ways.
    """
    root = get_for_org(models.CoordinateSystem, info, id=coordinate_system)

    systems, transformations = graph_logic.traverse(
        root,
        organization=info.context.request.organization,
        max_depth=max_depth,
    )

    return types.CoordinateGraph(root=root, systems=systems, transformations=transformations)


def lineage_graph(
    info: Info,
    coordinate_system: strawberry.ID,
    max_depth: int | None = None,
) -> types.LineageGraph:
    """Walk the derivation edges out from one container and return the provenance component.

    `coordinateGraph` answers "which edges relate to this space"; this answers "where did
    this data come from, and what came out of it" -- and the difference is which edges are
    crossed. That one walks everything touching a space, so a registration drags in every
    other dataset registered into the same world, which is a neighbourhood and not a
    lineage. This walks derivation edges only, in both directions, and hands back
    *containers* rather than spaces: a dataset's grid, its levels and its lenses are one
    node in a provenance story rather than three.

    Rooted at a coordinate system for the same reason `coordinateGraph` and
    `attributePlans` are: every container has one and it is the one identifier that means
    the same thing for a dataset, a table, a mesh and an annotation collection. Pass
    `dataset.intrinsicSystem.id`, `tableDataset.coordinateSystem.id`, and so on.

    It composes nothing, and it is not scene-scoped. Provenance is a fact about the data,
    and two scenes cannot disagree about what a thing was computed from.
    """
    root = get_for_org(models.CoordinateSystem, info, id=coordinate_system)

    nodes, edges = graph_logic.lineage_graph(
        root,
        organization=info.context.request.organization,
        max_depth=max_depth,
    )

    return types.LineageGraph(root=root, nodes=nodes, edges=edges)
