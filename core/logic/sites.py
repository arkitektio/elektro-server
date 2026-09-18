"""Recording and stimulus sites: places *in* a neuron model.

A site names its model and addresses a place in it the way NEURON does: a cell of the model's
config, a section of that cell, a position along the section. The model is the authority on
which cells and sections exist, so a site is checked against the model's ``json_model`` when it
is written -- a site on a section the model does not have describes nothing.

The config is read as the stored JSON (``cells[].id``, ``cells[].topology.sections[].id``),
not re-validated as a ``ModelConfigModel``: the ids are all a site needs, and a model whose
config predates a field of the pydantic model must not make its sites unwritable.
"""

from core import models


def cells_of(model: "models.NeuronModel") -> dict[str, dict]:
    """The cells the model's config declares, by id."""
    config = model.json_model if isinstance(model.json_model, dict) else {}
    return {cell["id"]: cell for cell in config.get("cells") or [] if isinstance(cell, dict) and isinstance(cell.get("id"), str)}


def sections_of(cell: dict) -> list[str]:
    """The section ids of one cell of a model's config, in the config's order."""
    topology = cell.get("topology") if isinstance(cell.get("topology"), dict) else {}
    return [section["id"] for section in topology.get("sections") or [] if isinstance(section, dict) and isinstance(section.get("id"), str)]


def assert_site_on_model(model: "models.NeuronModel", *, cell: str | None, location: str | None) -> None:
    """Refuse a site that names a cell or a section its model does not declare.

    ``location`` without ``cell`` is read on the model's only cell; with several cells the
    section id alone is ambiguous, and the cell is asked for. Neither given is a site on the
    model as a whole -- said, not guessed.
    """
    cells = cells_of(model)
    if cell is not None and cell not in cells:
        raise ValueError(f"A site is part of its neuron model, and model '{model.name}' has no cell '{cell}'. Its cells are {sorted(cells) or 'none: its config declares no cells'}.")
    if location is None:
        return
    if cell is None:
        if len(cells) != 1:
            raise ValueError(
                f"The site names section '{location}' but no cell, and model '{model.name}' has {len(cells)} cells ({sorted(cells)}). Name the `cell` the section belongs to."
                if cells
                else f"A site is part of its neuron model, and model '{model.name}' declares no cells, so it has no section '{location}'."
            )
        (cell,) = cells
    sections = sections_of(cells[cell])
    if location not in sections:
        raise ValueError(f"A site is part of its neuron model, and cell '{cell}' of model '{model.name}' has no section '{location}'. Its sections are {sections or 'none'}.")
