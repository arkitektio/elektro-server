"""elektro as the hub's rekuest sees it (vendored ``rekuest_service``): the service, and its HookAgent.

Two declarations, read by rekuest from one manifest and mounted by ``urls.py`` (``*service.urls``):

* the **service** says what exists: the structures elektro hosts, the descriptors of their objects,
  and — every save and delete being announced, with no emit in the mutations — the signals it
  emits. Hub-wide; users' triggers are checked against the kinds and descriptor keys declared here,
  and the GraphQL types answer ``descriptors`` from the same declarations (``core.types``);
* its **agent** says what can be done: the actions rekuest runs here. Every organization has the
  agent and its own schedules, so an action does one organization's share of the work.

Nothing here loops: each run is one pass rekuest started, and a lost run is followed by the next.
"""

from django.conf import settings

from core import models
from core.descriptors import ARRAY_DESCRIPTORS, dataset_descriptors, lens_descriptors
from embeddings import engine
from embeddings.healer import reembed_all
from rekuest_service import HookAgent, Service, organization_of

service = Service("elektro", description="Electrophysiology data and simulations.")

# The models whose name + description are embedded (see ``embeddings.healer``).
_EMBEDDED_MODELS = (models.ArrayDataset, models.TableDataset, models.SparseDataset)


# --- Structures ---------------------------------------------------------------------------

ALL = ("CREATED", "UPDATED", "DELETED")
CREATED_DELETED = ("CREATED", "DELETED")
org = organization_of()

service.structure(
    models.ArrayDataset,
    "@elektro/arraydataset",
    kinds=ALL,
    organization=org,
    descriptors=ARRAY_DESCRIPTORS,
    describe=dataset_descriptors,
    description="A multi-dimensional array dataset: a recording, a stimulus or a simulation trace, on its sample grid.",
    signal_description="An array dataset (a recording, a simulation trace) was created, changed or deleted, with its axis counts and extents.",
)
service.structure(
    models.Lens,
    "@elektro/lens",
    # Hosted, not signalled: a lens is a way of looking at a dataset, and it is the dataset whose arrival is news.
    kinds=(),
    descriptors=ARRAY_DESCRIPTORS,
    describe=lens_descriptors,
    description="A selection over an array dataset: a sweep, an epoch window, a run of channels.",
)
service.structure(
    models.TableDataset,
    "@elektro/tabledataset",
    kinds=ALL,
    organization=org,
    description="A parquet-backed table of scientific records.",
    signal_description="A table dataset was created, changed or deleted.",
)
service.structure(
    models.SparseDataset,
    "@elektro/sparsedataset",
    kinds=CREATED_DELETED,
    organization=org,
    description="A sparse dataset, such as a spike raster.",
    signal_description="A sparse dataset was created or deleted.",
)
service.structure(
    models.NeuronModel,
    "@elektro/neuronmodel",
    kinds=("CREATED",),
    organization=org,
    description="A neuron model: the cells, biophysics and topology a simulation runs.",
    signal_description="A neuron model was registered.",
)
service.structure(
    models.ModelCollection,
    "@elektro/modelcollection",
    kinds=("CREATED",),
    organization=org,
    description="A named collection of neuron models.",
    signal_description="A model collection was created.",
)
service.structure(
    models.Experiment,
    "@elektro/experiment",
    kinds=ALL,
    organization=org,
    description="Data laid out on one timeline, as layers.",
    signal_description="An experiment was created, changed or deleted.",
)
service.structure(
    models.File,
    "@elektro/file",
    kinds=CREATED_DELETED,
    organization=org,
    description="A file in its original format, as it was uploaded.",
    signal_description="A file was uploaded or deleted.",
)
service.structure(
    models.Folder,
    "@elektro/folder",
    kinds=ALL,
    organization=org,
    description="A folder: where a user files the things elektro stores.",
    signal_description="A folder was created, changed or deleted.",
)
service.structure(
    models.AnnotationCollection,
    "@elektro/annotationcollection",
    kinds=CREATED_DELETED,
    organization=org,
    description="A named set of annotations, owning the space they are drawn in.",
    signal_description="An annotation collection was created or deleted.",
)


# --- The HookAgent ------------------------------------------------------------------------

agent = HookAgent(service)


@agent.action(
    interface="reembed_stale",
    name="Re-embed stale rows",
    description="Re-embed every row of the organization whose vector was produced by another embedding model, or by none.",
    # Scheduled only where embeddings are on; ``embeddings.sweep_interval`` is its cadence.
    default_interval=settings.EMBEDDINGS["SWEEP_INTERVAL"] if engine.enabled() else None,
)
def reembed_stale(organization: str) -> dict:
    """One pass over the organization's embedded rows, in row-locked batches (N replicas may run it at once)."""
    return {"reembedded": reembed_all(_EMBEDDED_MODELS, max_batches=50, organization=organization)}
