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


from core import models
from core.descriptors import dataset_descriptors, lens_descriptors
from arkitekt_service.service import Service, organization_of

from elektro_server.contract import contract

service = Service("elektro", hosts=contract.description.hosts, description="Electrophysiology data and simulations.")


# --- Structures: what elektro hosts ---------------------------------------------------

arraydataset = service.structure(models.ArrayDataset, "@elektro/arraydataset", describe=dataset_descriptors)
# Hosted, never announced: a lens is a way of looking at a dataset, and it is the dataset whose arrival is news.
lens = service.structure(models.Lens, "@elektro/lens", describe=lens_descriptors)
tabledataset = service.structure(models.TableDataset, "@elektro/tabledataset")
sparsedataset = service.structure(models.SparseDataset, "@elektro/sparsedataset")
neuronmodel = service.structure(models.NeuronModel, "@elektro/neuronmodel")
modelcollection = service.structure(models.ModelCollection, "@elektro/modelcollection")
experiment = service.structure(models.Experiment, "@elektro/experiment")
file = service.structure(models.File, "@elektro/file")
folder = service.structure(models.Folder, "@elektro/folder")
annotationcollection = service.structure(models.AnnotationCollection, "@elektro/annotationcollection")


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
