"""elektro as the hub's rekuest sees it: the actions it offers, the signals it emits (vendored ``rekuest_service``).

Like an arkitekt ``App``: one ``Service`` declaration, mounted by ``urls.py`` (``*service.urls``),
read by rekuest from the manifest. Nothing here loops: each run is one pass rekuest started, and
a lost run is followed by the next.
"""

from django.conf import settings

from core import models
from core.descriptors import ARRAY_DESCRIPTOR_KEYS, array_descriptors
from embeddings import engine
from embeddings.healer import reembed_all
from rekuest_service import Service, organization_of

service = Service("elektro", description="Electrophysiology data and simulations.")

# The models whose name + description are embedded (see ``embeddings.healer``).
_EMBEDDED_MODELS = (models.ArrayDataset, models.TableDataset, models.SparseDataset)


# --- Signals ------------------------------------------------------------------------------
# What elektro announces to the hub's rekuest: every save and delete of these models.

ALL = ("CREATED", "UPDATED", "DELETED")
CREATED_DELETED = ("CREATED", "DELETED")
org = organization_of()


def _dataset_descriptors(dataset: models.ArrayDataset) -> dict:
    """The client's axis vocabulary, from the row (read at commit: the axes are written after it)."""
    try:
        return array_descriptors([axis.type for axis in dataset.axes], dataset.shape_list)
    except ValueError:
        return {}


service.model_signal(
    models.ArrayDataset,
    "@elektro/arraydataset",
    kinds=ALL,
    organization=org,
    descriptors=_dataset_descriptors,
    descriptor_keys=ARRAY_DESCRIPTOR_KEYS,
    description="An array dataset (a recording, a simulation trace) was created, changed or deleted, with its axis counts and extents.",
)
service.model_signal(models.TableDataset, "@elektro/tabledataset", kinds=ALL, organization=org, description="A table dataset was created, changed or deleted.")
service.model_signal(models.SparseDataset, "@elektro/sparsedataset", kinds=CREATED_DELETED, organization=org, description="A sparse dataset was created or deleted.")
service.model_signal(models.NeuronModel, "@elektro/neuronmodel", kinds=("CREATED",), organization=org, description="A neuron model was registered.")
service.model_signal(models.ModelCollection, "@elektro/modelcollection", kinds=("CREATED",), organization=org, description="A model collection was created.")
service.model_signal(models.Experiment, "@elektro/experiment", kinds=ALL, organization=org, description="An experiment was created, changed or deleted.")
service.model_signal(models.File, "@elektro/file", kinds=CREATED_DELETED, organization=org, description="A file was uploaded or deleted.")
service.model_signal(models.Folder, "@elektro/dataset", kinds=ALL, organization=org, description="A folder (dataset) was created, changed or deleted.")
service.model_signal(models.AnnotationCollection, "@elektro/annotationcollection", kinds=CREATED_DELETED, organization=org, description="An annotation collection was created or deleted.")


@service.action(
    interface="reembed_stale",
    name="Re-embed stale rows",
    description="Re-embed every row whose vector was produced by another embedding model, or by none.",
    # Scheduled only where embeddings are on; ``embeddings.sweep_interval`` is its cadence.
    default_interval=settings.EMBEDDINGS["SWEEP_INTERVAL"] if engine.enabled() else None,
)
def reembed_stale() -> dict:
    """One pass over every embedded model, in row-locked batches (N replicas may run it at once)."""
    return {"reembedded": reembed_all(_EMBEDDED_MODELS, max_batches=50)}
