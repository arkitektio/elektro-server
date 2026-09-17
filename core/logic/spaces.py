"""The life of a space that nothing owns: when it goes.

Elektro's own, and deliberately small. Under residence a space does not belong to the data in
it -- the FK runs data -> space and is PROTECT -- so deleting data can never cascade into its
space, and a sample grid with no dataset in it is not a space anyone can use. mikro leaves
those to an orphan sweep; here the delete mutations sweep the spaces they just emptied, so
the sampling law and the offsets that touched them go in the same request.
"""

from django.db.models import Q

from core import models
from core.logic import graph as graph_logic


def sweep_empty_systems(system_ids) -> list[int]:  # noqa: ANN001 - any iterable of ids
    """Delete, among these systems, the ones that are now nobody's: nothing lives in them and nothing is laid out over them.

    Called by a delete *after* the data is gone, with the systems that data lived in or was
    timed against. It is how a space leaves with its data, given that nothing owns a space:
    a dataset's FK to its grid is PROTECT and a block's to its clock is RESTRICT, so neither
    can cascade, and a sample grid with no dataset in it is not a space anyone can use. The
    edges touching a swept system cascade with it -- the sampling law, the offset.

    Both tests come from the graph's own registries (``RESIDENT_RELATIONS``,
    ``WORLD_RELATIONS``), so a new kind of resident or composition is protected from this
    sweep by the line that declares it. A frame another dataset still lives in, or a
    session clock another block shares, is left exactly where it is.
    """
    ids = {system_id for system_id in system_ids if system_id is not None}
    if not ids:
        return []
    unused = {f"{relation}__isnull": True for relation in (*graph_logic.RESIDENT_RELATIONS, *graph_logic.WORLD_RELATIONS)}
    empty = list(models.CoordinateSystem.objects.filter(pk__in=ids, **unused).values_list("pk", flat=True))

    # The edges first, then the spaces. They would cascade with the spaces anyway -- except
    # that a time lookup holds its *field* under PROTECT (so a times dataset's system cannot be
    # deleted out from under the edge reading it), and PROTECT, unlike RESTRICT, refuses even
    # when the protecting row is going in the same delete. So a signal's grid and its times
    # dataset's system, swept together, have to lose the edge between them before either goes.
    models.Transformation.objects.filter(Q(input_id__in=empty) | Q(output_id__in=empty)).delete()
    # What a lookup elsewhere still reads through stays: the edge is a fact about data that
    # still exists, and the honest state is a field system nothing lives in -- which
    # `assert_field_is_dereferenceable` names, and which the orphan sweep leaves alone too.
    # The same for a space an annotation collection's bounding boxes are denominated in
    # (`AnnotationCollection.bbox_system`, PROTECT): deleting a dataset must not silently
    # relabel the numbers of the marks drawn over it. The emptied grid stays, holding the frame.
    empty = list(models.CoordinateSystem.objects.filter(pk__in=empty, fields_of__isnull=True, annotation_bbox_frames__isnull=True).values_list("pk", flat=True))
    models.CoordinateSystem.objects.filter(pk__in=empty).delete()
    return empty
