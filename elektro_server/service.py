"""elektro as a service of the hub: the models and the code behind what its contract says it hosts.

What exists here (the structures, the descriptors of their objects, the signals and their kinds)
is declared once, as data, in ``elektro_server.contract`` (``hosts``), so that a hub knows it from the
image. This module only binds it: each structure to its model and to what computes its
descriptors, each signal to the saves and deletes that send it. A structure the contract does not
declare cannot be bound, and one it declares that nothing binds here stops the service at its
start. The GraphQL types answer ``descriptors`` from the same binding (``core.types``).

Hosting announces nothing by itself: a structure with no signal below is hosted silently.

That is all a service is. What can be *done* in this process is not declared here: that is an
agent's to say (``elektro_server.hook_agent``), a different thing with its own configuration.
"""


from django.contrib.contenttypes.models import ContentType
from django.db.models import Model, Q
from django.db.models.signals import m2m_changed, post_save

from core import models
from core.descriptors import dataset_descriptors, lens_descriptors
from arkitekt_service.service import Service, organization_of
from arkitekt_service.collaborations import items as collaboration_items
from arkitekt_service.collaborations.models import CollaborationItem

from elektro_server.contract import contract

service = Service("elektro", hosts=contract.description.hosts, description="Electrophysiology data and simulations.")


# --- Collaborations: what an object needs to be seen, put in a collaboration along with it ------------------
# What is part of an object (a dataset's arrays and lenses, an experiment's layers, a collection's
# annotations, an anchor's spokes) is in a collaboration with it by itself. These name the rest:
# what it points at to be read and drawn (a None among them is dropped).


def _edge(edge: models.Transformation) -> list[models.Transformation]:
    """An edge with its steps, and theirs: a wrapper's children are part of nothing (``parent`` is nullable)."""
    return [edge, *(step for child in edge.children.all() for step in _edge(child))]


def _space(system: models.CoordinateSystem | None) -> list[Model]:
    """A coordinate system, and what places it: the edges out of it, with their steps, and the spaces
    they lead to, onward (a sample grid, its clock, the clock it is synced onto, the world).

    In mikro an edge is part of the space it leaves; here ``input`` is nullable (a wrapper's child
    has none), so an edge is part of nothing and is brought along with its input instead. Only
    outward: the edges into a space are other data's, registered there.
    """
    found: list[Model] = []
    frontier = [system] if system is not None else []
    seen: set[int] = set()
    while frontier:
        current = frontier.pop()
        if current.pk in seen:
            continue
        seen.add(current.pk)
        found.append(current)
        for edge in models.Transformation.objects.filter(input=current, parent__isnull=True).select_related("output"):
            found.extend(_edge(edge))
            if edge.output is not None:
                frontier.append(edge.output)
    return found


def _anchored(anchors: list[models.CoordinateAnchor]) -> list[Model]:
    """A container's anchors (their spokes are part of them), and the neuron models a run's spokes name."""
    simulated = models.NeuronModel.objects.filter(Q(simulation_states__anchor__in=anchors) | Q(recording_sites__anchor__in=anchors) | Q(stimulus_sites__anchor__in=anchors)).distinct()
    return [*anchors, *simulated]


def _dataset_needs(dataset: models.ArrayDataset) -> list[Model | None]:
    """A dataset's grid, each array's store and grid, each lens' grid, and its anchors."""
    needed: list[Model | None] = [*_space(dataset.coordinate_system)]
    for array in dataset.data_arrays.select_related("store", "coordinate_system"):
        needed.extend([array.store, *_space(array.coordinate_system)])
    for lens in dataset.lenses.select_related("coordinate_system"):
        needed.extend(_space(lens.coordinate_system))
    return [*needed, *_anchored(list(dataset.anchors.all()))]


def _lens_needs(lens: models.Lens) -> list[Model]:
    """A lens' grid and the edge back to its dataset's. The lens is part of its dataset, not the other way round."""
    return _space(lens.coordinate_system)


def _table_needs(table: models.TableDataset) -> list[Model]:
    """A table's store and grid, the tables its columns identify rows of, and its anchors."""
    referenced = models.TableDataset.objects.filter(referenced_by__table=table).exclude(pk=table.pk).distinct()
    return [table.store, *_space(table.coordinate_system), *referenced, *_anchored(list(table.anchors.all()))]


def _sparse_needs(sparse: models.SparseDataset) -> list[Model]:
    """A sparse dataset's stores and grid, the tables its axes enumerate (a raster's unit table), and its anchors."""
    stores = [array.store for array in sparse.arrays.select_related("store")]
    referenced = models.TableDataset.objects.filter(referenced_by_sparse_axes__dataset=sparse).distinct()
    return [*stores, *_space(sparse.coordinate_system), *referenced, *_anchored(list(sparse.anchors.all()))]


def _collection_needs(collection: models.AnnotationCollection) -> list[Model]:
    """The space a collection's shapes are drawn in, and its bounding boxes'."""
    return [*_space(collection.coordinate_system), *_space(collection.bbox_system)]


def _experiment_needs(experiment: models.Experiment) -> list[Model | None]:
    """An experiment's timeline, what each of its layers draws (a trace: the dataset its lens is over), and its drawing surface."""
    needed: list[Model | None] = [*_space(experiment.world)]
    for layer in experiment.layers.select_related("lens__dataset", "sparse_dataset", "table_dataset", "annotation_collection"):
        needed.extend([layer.lens.dataset if layer.lens is not None else None, layer.sparse_dataset, layer.table_dataset, layer.annotation_collection])
    needed.extend(models.AnnotationCollection.objects.filter(experiment=experiment))
    return needed


def _neuron_model_needs(model: models.NeuronModel) -> list[Model | None]:
    """The mod environment a model is simulated with (its mechanisms are part of it), its file, and the model's own space."""
    return [model.environment, model.environment.store, *_space(model.coordinate_system)]


def _model_collection_needs(collection: models.ModelCollection) -> list[Model | None]:
    """The models in a collection, and the one they are compared against."""
    return [collection.comparison, *collection.models.all()]


def _file_needs(file: models.File) -> list[Model | None]:
    """The store holding a file's bytes."""
    return [file.store]


# --- Structures: what elektro hosts ---------------------------------------------------

arraydataset = service.structure(models.ArrayDataset, "@elektro/arraydataset", describe=dataset_descriptors, depends=_dataset_needs)
# Hosted, never announced: a lens is a way of looking at a dataset, and it is the dataset whose arrival is news.
lens = service.structure(models.Lens, "@elektro/lens", describe=lens_descriptors, depends=_lens_needs)
tabledataset = service.structure(models.TableDataset, "@elektro/tabledataset", depends=_table_needs)
sparsedataset = service.structure(models.SparseDataset, "@elektro/sparsedataset", depends=_sparse_needs)
neuronmodel = service.structure(models.NeuronModel, "@elektro/neuronmodel", depends=_neuron_model_needs)
modelcollection = service.structure(models.ModelCollection, "@elektro/modelcollection", depends=_model_collection_needs)
experiment = service.structure(models.Experiment, "@elektro/experiment", depends=_experiment_needs)
file = service.structure(models.File, "@elektro/file", depends=_file_needs)
folder = service.structure(models.Folder, "@elektro/folder")
annotationcollection = service.structure(models.AnnotationCollection, "@elektro/annotationcollection", depends=_collection_needs)


# --- Signals: what elektro announces ---------------------------------------------------

org = organization_of()

service.model_signal(arraydataset, organization=org)
service.model_signal(tabledataset, organization=org)
service.model_signal(sparsedataset, organization=org)
service.model_signal(neuronmodel, organization=org)
service.model_signal(modelcollection, organization=org)
service.model_signal(experiment, organization=org)
service.model_signal(file, organization=org)
service.model_signal(folder, organization=org)
service.model_signal(annotationcollection, organization=org)


# Cascading keys that point at something shared, not at a whole: a run's sites and state are its
# dataset's, not part of the neuron model many runs simulate; a model is not part of the mod
# environment many models are simulated with; a mapping is its workspace's, not its model's.
service.not_part_of(models.RecordingSite, "model")
service.not_part_of(models.StimulusSite, "model")
service.not_part_of(models.SimulationState, "model")
service.not_part_of(models.NeuronModel, "environment")
service.not_part_of(models.WorkspaceMapping, "model")


# What a part added later brings: each of these, saved, changes what its whole needs to be seen,
# and the whole's collaborations get it (``refresh``).


def _layer_saved(sender: object, instance: models.ExperimentLayer, raw: bool = False, **_: object) -> None:
    """A layer added to (or changed in) an experiment in a collaboration brings what it draws into that collaboration."""
    if not raw:
        collaboration_items.refresh(instance.experiment)


def _level_or_lens_saved(sender: object, instance: models.DataArray | models.Lens, raw: bool = False, **_: object) -> None:
    """A pyramid level or a lens added to a dataset in a collaboration brings its store and its grid."""
    if not raw:
        collaboration_items.refresh(instance.dataset)


def _anchor_saved(sender: object, instance: models.CoordinateAnchor, raw: bool = False, **_: object) -> None:
    """An anchor pinned into a container in a collaboration comes into it, with its spokes."""
    if not raw:
        collaboration_items.refresh(instance.container)


def _site_saved(sender: object, instance: models.RecordingSite | models.StimulusSite | models.SimulationState, raw: bool = False, **_: object) -> None:
    """A run's site or state, hung on an anchor of a container in a collaboration, brings the neuron model it names."""
    if not raw:
        collaboration_items.refresh(instance.anchor.container)


def _models_changed(sender: object, instance: models.ModelCollection, action: str, reverse: bool = False, **_: object) -> None:
    """Models put in a collection in a collaboration come into it."""
    if action == "post_add" and not reverse:
        collaboration_items.refresh(instance)


def _edge_saved(sender: object, instance: models.Transformation, raw: bool = False, **_: object) -> None:
    """An edge comes into every collaboration the space it leaves is in, with the spaces it leads to;
    a wrapper's step, into every collaboration its wrapper is in."""
    if raw:
        return
    if instance.parent_id is not None:
        collaboration_items.include(instance, alongside=instance.parent)
        return
    if instance.input_id is None:
        return
    holding = CollaborationItem.objects.filter(content_type=ContentType.objects.get_for_model(models.CoordinateSystem), object_id=str(instance.input_id)).select_related("collaboration")
    if not holding.exists():
        return
    brought = [*_edge(instance), *_space(instance.output)]
    for item in holding:
        for obj in brought:
            collaboration_items.add(item.collaboration, obj, because_of=item)


post_save.connect(_layer_saved, sender=models.ExperimentLayer, dispatch_uid="elektro-collaborations-layer")
post_save.connect(_level_or_lens_saved, sender=models.DataArray, dispatch_uid="elektro-collaborations-level")
post_save.connect(_level_or_lens_saved, sender=models.Lens, dispatch_uid="elektro-collaborations-lens")
post_save.connect(_anchor_saved, sender=models.CoordinateAnchor, dispatch_uid="elektro-collaborations-anchor")
post_save.connect(_site_saved, sender=models.RecordingSite, dispatch_uid="elektro-collaborations-recording-site")
post_save.connect(_site_saved, sender=models.StimulusSite, dispatch_uid="elektro-collaborations-stimulus-site")
post_save.connect(_site_saved, sender=models.SimulationState, dispatch_uid="elektro-collaborations-simulation")
post_save.connect(_edge_saved, sender=models.Transformation, dispatch_uid="elektro-collaborations-edge")
m2m_changed.connect(_models_changed, sender=models.ModelCollection.models.through, dispatch_uid="elektro-collaborations-models")
