"""Recording and stimulus sites: places *in* a neuron model.

A site names its model and addresses a place in it the way NEURON does: a cell of the model's
config, a section of that cell, a position along the section. The model is the authority on
which cells and sections exist, so a site is checked against the model's ``json_model`` when it
is written -- a site on a section the model does not have describes nothing.

The config is read as the stored JSON (``cells[].id``, ``cells[].topology.sections[].id``),
not re-validated as a ``ModelConfigModel``: the ids are all a site needs, and a model whose
config predates a field of the pydantic model must not make its sites unwritable.
"""

from urllib.parse import quote, unquote

from django.db.models import Q

from core import models
from core.base_models.type.model import ModelConfigModel


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


def config_of(model: "models.NeuronModel") -> ModelConfigModel:
    """The model's config, each cell and section stamped with the model (and cell) it was read from.

    The GraphQL ``Cell`` / ``Section`` are pydantic objects with no way back to the row they
    came from; their ``sessions`` need one. The stamp is a private attribute, so it is never
    serialized and never reaches ``json_model``.
    """
    config = ModelConfigModel(**model.json_model)
    sole = len(config.cells) == 1
    for cell in config.cells:
        cell._neuron_model_id, cell._sole_cell = model.pk, sole
        for section in cell.topology.sections:
            section._neuron_model_id, section._cell_id, section._sole_cell = model.pk, cell.id, sole
    return config


def recorded_dataset_ids(model_id: int, *, cell: str, location: str | None = None, sole_cell: bool = False) -> "models.QuerySet":
    """The ids of the datasets with a recording site on this cell (and section) of the model.

    A site that names no cell is on the model's only cell -- the reading
    :func:`assert_site_on_model` gave it when it was written -- so it counts for the sole cell.
    """
    on_cell = Q(cell=cell) | (Q(cell__isnull=True) if sole_cell else Q(pk__in=[]))
    sites = models.RecordingSite.objects.filter(on_cell, model_id=model_id)
    if location is not None:
        sites = sites.filter(location=location)
    return sites.values("anchor__dataset_id")


def sessions_of(datasets: list) -> list[tuple["models.CoordinateSystem | None", list]]:
    """Group datasets by the clock they are timed onto -- one session per run -- in clock order.

    A dataset timed onto two clocks is in both; those timed onto none come last, under ``None``.
    Two queries whatever the count: the datasets are the caller's, the clocks one batched read.
    """
    from core.logic import clocks

    by_grid = clocks.timing_clocks_by_grid(dataset.coordinate_system_id for dataset in datasets)
    grouped: dict[int, tuple] = {}
    untimed: list = []
    for dataset in datasets:
        timed_on = by_grid.get(dataset.coordinate_system_id, [])
        if not timed_on:
            untimed.append(dataset)
        for clock in timed_on:
            grouped.setdefault(clock.pk, (clock, []))[1].append(dataset)
    return [grouped[pk] for pk in sorted(grouped)] + ([(None, untimed)] if untimed else [])


# --- compound ids: a cell or section of a stored model, addressed from outside it -------------

_SEPARATOR = ":"


def compound_id(model_id: int, cell: str, section: str | None = None) -> str:
    """``model:cell`` or ``model:cell:section``, each part percent-encoded.

    A cell or section id is only unique within its model (``soma`` is in most of them), so it
    cannot address one from outside. Encoding each part keeps a ``:`` inside an id from
    making the compound ambiguous; the model's id is a primary key and needs none.
    """
    parts = [str(model_id), quote(cell, safe="")] + ([quote(section, safe="")] if section is not None else [])
    return _SEPARATOR.join(parts)


def parse_compound_id(value: str, *, parts: int) -> tuple[str, ...]:
    """Split a compound id into its ``parts`` decoded components, or refuse it."""
    split = str(value).split(_SEPARATOR)
    if len(split) != parts or not all(split):
        shape = "model:cell" if parts == 2 else "model:cell:section"
        raise ValueError(f"'{value}' is not a compound id of the form '{shape}' (each part percent-encoded).")
    return tuple(unquote(part) for part in split)


def cell_of(model: "models.NeuronModel", cell_id: str):  # noqa: ANN201 - a stamped CellModel
    """The stamped cell ``cell_id`` of ``model``'s config, or a refusal naming the cells it has."""
    config = config_of(model)
    for cell in config.cells:
        if cell.id == cell_id:
            return cell
    raise ValueError(f"Model '{model.name}' has no cell '{cell_id}'. Its cells are {sorted(cell.id for cell in config.cells)}.")


def section_of(model: "models.NeuronModel", cell_id: str, section_id: str):  # noqa: ANN201 - a stamped SectionModel
    """The stamped section ``section_id`` of cell ``cell_id``, or a refusal naming the sections it has."""
    cell = cell_of(model, cell_id)
    for section in cell.topology.sections:
        if section.id == section_id:
            return section
    raise ValueError(f"Cell '{cell_id}' of model '{model.name}' has no section '{section_id}'. Its sections are {[section.id for section in cell.topology.sections]}.")
