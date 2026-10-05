"""elektro as a service of the hub: what exists here (``arkitekt_service.service``).

Two separate declarations, read by rekuest from the service's manifest (``*service.urls`` in
``urls.py``) and catalogued hub-wide:

* the **structures** elektro hosts, and the descriptors of their objects. The GraphQL types answer
  ``descriptors`` from the same declarations (``core.types``);
* the **signals** it emits: which saves and deletes are announced, with no emit in the mutations.
  Users' triggers are checked against the kinds and descriptor keys declared here.

Hosting announces nothing by itself: a structure with no signal below is hosted silently.

That is all a service is. What can be *done* in this process is not declared here: that is an
agent's to say (``elektro_server.hook_agent``), a different thing with its own configuration.
"""


from core import models
from core.descriptors import ARRAY_DESCRIPTORS, dataset_descriptors, lens_descriptors
from arkitekt_service.service import Service, organization_of

service = Service("elektro", description="Electrophysiology data and simulations.")


# --- Structures: what elektro hosts ---------------------------------------------------

arraydataset = service.structure(
    models.ArrayDataset,
    "@elektro/arraydataset",
    descriptors=ARRAY_DESCRIPTORS,
    describe=dataset_descriptors,
    description="A multi-dimensional array dataset: a recording, a stimulus or a simulation trace, on its sample grid.",
)
# Hosted, never announced: a lens is a way of looking at a dataset, and it is the dataset whose arrival is news.
lens = service.structure(
    models.Lens,
    "@elektro/lens",
    descriptors=ARRAY_DESCRIPTORS,
    describe=lens_descriptors,
    description="A selection over an array dataset: a sweep, an epoch window, a run of channels.",
)
tabledataset = service.structure(
    models.TableDataset,
    "@elektro/tabledataset",
    description="A parquet-backed table of scientific records.",
)
sparsedataset = service.structure(
    models.SparseDataset,
    "@elektro/sparsedataset",
    description="A sparse dataset, such as a spike raster.",
)
neuronmodel = service.structure(
    models.NeuronModel,
    "@elektro/neuronmodel",
    description="A neuron model: the cells, biophysics and topology a simulation runs.",
)
modelcollection = service.structure(
    models.ModelCollection,
    "@elektro/modelcollection",
    description="A named collection of neuron models.",
)
experiment = service.structure(
    models.Experiment,
    "@elektro/experiment",
    description="Data laid out on one timeline, as layers.",
)
file = service.structure(
    models.File,
    "@elektro/file",
    description="A file in its original format, as it was uploaded.",
)
folder = service.structure(
    models.Folder,
    "@elektro/folder",
    description="A folder: where a user files the things elektro stores.",
)
annotationcollection = service.structure(
    models.AnnotationCollection,
    "@elektro/annotationcollection",
    description="A named set of annotations, owning the space they are drawn in.",
)


# --- Signals: what elektro announces ---------------------------------------------------

ALL = ("CREATED", "UPDATED", "DELETED")
CREATED_DELETED = ("CREATED", "DELETED")
org = organization_of()

service.model_signal(
    arraydataset,
    kinds=ALL,
    organization=org,
    description="An array dataset (a recording, a simulation trace) was created, changed or deleted, with its axis counts and extents.",
)
service.model_signal(
    tabledataset,
    kinds=ALL,
    organization=org,
    description="A table dataset was created, changed or deleted.",
)
service.model_signal(
    sparsedataset,
    kinds=CREATED_DELETED,
    organization=org,
    description="A sparse dataset was created or deleted.",
)
service.model_signal(
    neuronmodel,
    kinds=("CREATED",),
    organization=org,
    description="A neuron model was registered.",
)
service.model_signal(
    modelcollection,
    kinds=("CREATED",),
    organization=org,
    description="A model collection was created.",
)
service.model_signal(
    experiment,
    kinds=ALL,
    organization=org,
    description="An experiment was created, changed or deleted.",
)
service.model_signal(
    file,
    kinds=CREATED_DELETED,
    organization=org,
    description="A file was uploaded or deleted.",
)
service.model_signal(
    folder,
    kinds=ALL,
    organization=org,
    description="A folder was created, changed or deleted.",
)
service.model_signal(
    annotationcollection,
    kinds=CREATED_DELETED,
    organization=org,
    description="An annotation collection was created or deleted.",
)
