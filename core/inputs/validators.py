"""The value rules that repeat across inputs: colours, and the geometry of a drawn shape.

Vendored from mikro's ``core/inputs/validators.py``, keeping what an annotation needs. Plain
functions rather than pydantic types: a resolver's exception reaches the client as
``errors[0].message`` verbatim, so the message *is* the API contract, and a
``@field_validator`` calling one of these keeps the field's declared type exactly as the SDL
publishes it.

Every one of these rejects only what cannot be meaningful. An inverted pair of epoch
corners normalises, and an unusual-but-finite number is somebody's real measurement --
neither belongs here.
"""

#: An RGBA colour is four components. Named so the several colour checks cannot drift apart.
_RGBA_LENGTH = 4


def assert_rgba(color: list, *, field: str, maximum: float | None = None) -> None:
    """Reject a colour that is not four components, and optionally one out of range.

    ``maximum`` is passed only where the component range is actually written down --
    ``255`` for the integer colours. Where it is not, the length is still checkable:
    "RGBA" says four components whatever scale they are on.
    """
    if len(color) != _RGBA_LENGTH:
        raise ValueError(f"`{field}` is an RGBA colour, so it takes exactly {_RGBA_LENGTH} components (red, green, blue, alpha), but got {len(color)} ({color}).")

    if maximum is not None:
        out_of_range = [component for component in color if not 0 <= component <= maximum]
        if out_of_range:
            raise ValueError(f"`{field}`'s components run from 0 to {maximum}, but got {out_of_range} in {color}.")


#: The fewest vertices each shape kind can be drawn from, where its encoding says so. A kind
#: absent from this table takes the default of one: an EVENT is one instant and EVENTS carry
#: no count rule worth imposing. These are minimums, never exact counts -- an EPOCH reads
#: `vectors[:2]` and ignores the rest.
#:
#: **Every key must be an `AnnotationKindChoices` value**; `tests/test_architecture.py` holds
#: it to that, so a kind renamed in the enum cannot leave its rule behind under the old name.
_MINIMUM_VERTICES: dict[str, int] = {
    # Stored as two opposite corners, so one corner does not describe one: it would silently
    # yield a stretch of no length.
    "epoch": 2,
    # A line runs between two points, an open path needs two to have a direction, and a
    # closed polygon needs three to enclose anything.
    "line": 2,
    "path": 2,
    "polygon": 3,
}


def assert_shape_vectors(vectors: list, *, kind: str | None) -> None:
    """Reject a shape whose vertices cannot describe it.

    Two rules, both about geometry that is not merely unusual but unreadable:

    **Rectangular.** Every vertex must have the same number of components. The bounding box
    takes its dimension from the *first* point, so a later vertex that is longer raises an
    ``IndexError`` -- a 500, not an error -- and one that is shorter silently loses its
    trailing components from the box.

    **Enough vertices for the kind.** Only where the kind's encoding says a number; see
    :data:`_MINIMUM_VERTICES`.

    An **empty** ``vectors`` is left alone. It is not a malformed shape but a declared absence
    of geometry: the bounding box answers ``None`` for it by design, and ``nearestAnnotations``
    excludes such a shape on purpose ("nowhere, not near").

    Deliberately also *not* a check of the vertex width against the drawing space's axis
    count: an event with one component drawn into a ``(t, c)`` collection is an ordinary thing
    to want, and its `coordinates` pins are how it says which channel it is on.
    """
    if not vectors:
        return

    widths = {len(vector) for vector in vectors}
    if len(widths) > 1:
        raise ValueError(f"Every vertex of one shape has the same number of components, but `vectors` mixes widths {sorted(widths)}. The bounding box is taken at the width of the first vertex, so the others would be truncated or would overrun it.")
    if widths == {0}:
        raise ValueError("A vertex has at least one component -- the instant it marks -- but `vectors` holds empty vertices.")

    minimum = _MINIMUM_VERTICES.get(kind or "", 1)
    if len(vectors) < minimum:
        raise ValueError(f"A{'n' if (kind or '')[:1] in 'aeiou' else ''} {kind} is drawn from at least {minimum} vertices, but `vectors` has {len(vectors)}.")
