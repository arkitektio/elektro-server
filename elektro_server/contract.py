"""What this image answers a hub's installer: ``arkitekt-service <verb>`` (see ``arkitekt_service.contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from arkitekt_service.contract import JSON, Contract, Description, Descriptor, Facts, Hosts, Job, Needs, Offers, Role, Scope, Signal, Start, Structure, blocks

from elektro_server.configuration import Settings
from elektro_server.vocabulary import ARRAY_DESCRIPTORS, VALUE_DESCRIPTORS

#: What an app may do here on a user's behalf: defined at the coordination server when the hub
#: enrols. Every root field of the schema asks for one of them (`AuthExtension(scopes=...)`).
SCOPES = [
    Scope(key="elektro_read", description="See recordings, datasets, experiments, layers, annotations and neuron models."),
    Scope(key="elektro_write", description="Upload and change recordings, datasets, files, folders, experiments, layers, annotations and coordinate systems."),
    Scope(key="elektro_models", description="Build and change neuron models, mechanisms, mod environments and model workspaces."),
    Scope(key="elektro_share", description="Share electrophysiology data with people outside your organization through collaborations."),
    Scope(key="elektro_all", description="Do everything in Elektro on your behalf.", is_all_scope=True),
]

#: What a member of an organization may do here.
ROLES = [
    Role(key="elektro_admin", description="Full control of Elektro in this organization.", is_admin_role=True),
    Role(key="elektro_editor", description="Upload and change electrophysiology data and share it.", is_default_role=True),
    Role(key="elektro_modeler", description="Build and change neuron models and model workspaces."),
]

#: The role every write asks for, the one that builds neuron models without it, and the one holding all.
EDITOR = "elektro_editor"
MODELER = "elektro_modeler"
ADMIN = "elektro_admin"

#: What an array dataset and a lens carry: what is counted off their axes, and what their values are.
ARRAY_STRUCTURE_DESCRIPTORS = [*ARRAY_DESCRIPTORS, *VALUE_DESCRIPTORS]

#: What exists on a hub because this service is there: said here, as data, so the hub knows it from
#: the image. ``service.py`` binds each of these to its model and refuses anything not said here.
HOSTS = Hosts(
    structures=[
        Structure(
            identifier="@elektro/arraydataset",
            label="Array Dataset",
            description="A multi-dimensional array of samples: an electrophysiology recording such as a patch clamp voltage or current trace, a stimulus waveform or a simulation trace, on its grid of time, channel and other axes.",
            descriptors=ARRAY_STRUCTURE_DESCRIPTORS,
        ),
        Structure(
            identifier="@elektro/lens",
            label="Lens",
            description="A selection over an array dataset: one sweep, an epoch or time window, a range of channels of a trace.",
            descriptors=ARRAY_STRUCTURE_DESCRIPTORS,
        ),
        Structure(
            identifier="@elektro/tabledataset",
            label="Table Dataset",
            description="A table of records stored as parquet, such as detected events, trials or a spike sorter's units.",
        ),
        Structure(
            identifier="@elektro/sparsedataset",
            label="Sparse Dataset",
            description="A sparse matrix over two enumerated axes, mostly zeros, such as a spike raster.",
        ),
        Structure(
            identifier="@elektro/neuronmodel",
            label="Neuron Model",
            description="A neuron model for NEURON simulation: its cells, their sections (compartments), biophysics and mechanisms, as a simulation runs them.",
        ),
        Structure(
            identifier="@elektro/modelcollection",
            label="Model Collection",
            description="A named collection of neuron models that are compared against each other.",
        ),
        Structure(
            identifier="@elektro/experiment",
            label="Experiment",
            description="An experiment view: recordings, stimuli and simulation results laid out on one timeline as layers, such as traces, heatmaps, spike rasters and events.",
        ),
        Structure(
            identifier="@elektro/file",
            label="File",
            description="An uploaded file, kept in its original format as it was uploaded.",
        ),
        Structure(
            identifier="@elektro/folder",
            label="Folder",
            description="A folder that organizes datasets, annotations and uploaded files, like a directory.",
        ),
        Structure(
            identifier="@elektro/annotationcollection",
            label="Annotation Collection",
            description="A named set of hand-drawn annotations, such as marked events and epochs, owning the space they are drawn in.",
        ),
    ],
    signals=[
        Signal(
            identifier="@elektro/arraydataset",
            kinds=["CREATED", "UPDATED", "DELETED"],
            descriptors=[descriptor.key for descriptor in ARRAY_STRUCTURE_DESCRIPTORS],
            description="An array dataset (a recorded trace, a stimulus, a simulation trace) was created, changed or deleted, with its axis counts and extents.",
        ),
        Signal(
            identifier="@elektro/tabledataset",
            kinds=["CREATED", "UPDATED", "DELETED"],
            description="A table dataset (events, trials, sorted units) was created, changed or deleted.",
        ),
        Signal(
            identifier="@elektro/sparsedataset",
            kinds=["CREATED", "DELETED"],
            description="A sparse dataset, such as a spike raster, was created or deleted.",
        ),
        Signal(
            identifier="@elektro/neuronmodel",
            kinds=["CREATED"],
            description="A neuron model for NEURON simulation was registered.",
        ),
        Signal(
            identifier="@elektro/modelcollection",
            kinds=["CREATED"],
            description="A collection of neuron models was created.",
        ),
        Signal(
            identifier="@elektro/experiment",
            kinds=["CREATED", "UPDATED", "DELETED"],
            description="An experiment (a timeline of recording, stimulus and simulation layers) was created, changed or deleted.",
        ),
        Signal(
            identifier="@elektro/file",
            kinds=["CREATED", "DELETED"],
            description="A file was uploaded or deleted.",
        ),
        Signal(
            identifier="@elektro/folder",
            kinds=["CREATED", "UPDATED", "DELETED"],
            description="A folder was created, changed or deleted.",
        ),
        Signal(
            identifier="@elektro/annotationcollection",
            kinds=["CREATED", "DELETED"],
            description="An annotation collection (a set of hand-drawn annotations) was created or deleted.",
        ),
    ],
)


def render(facts: Facts) -> dict[str, JSON]:
    """This release's config for the hub ``facts`` describes."""
    document: dict[str, JSON] = blocks.server(facts)
    document["datalayer"] = blocks.datalayer(facts, "media", "zarr")
    document["instance"] = blocks.instance(facts)
    hook = blocks.rekuest_hook(facts)
    if hook is not None:
        document["rekuest_hook"] = hook
    return document


contract = Contract(
    description=Description(
        name="elektro",
        identifier="live.arkitekt.elektro",
        summary="Electrophysiology recordings and simulations.",
        needs=Needs(scopes=SCOPES, roles=ROLES, storage=["media", "zarr", "parquet", "bigfile"], instance_key=True, peers=["rekuest"]),
        offers=Offers(endpoints={"rekuest_service": "_rekuest/service", "rekuest_hook": "_rekuest/hook"}),
        requires={"rekuest": ">=6"},
        hosts=HOSTS,
    ),
    settings=Settings,
    render=render,
    # How this service is started: there is no script beside it. `arkitekt-service serve`
    # (and `debug`) become these, so they get the container's signals themselves.
    serve=Start(("daphne", "-b", "0.0.0.0", "-p", "80", "--websocket_timeout", "-1", "elektro_server.asgi:application")),
    debug=Start(("python", "manage.py", "runserver", "0.0.0.0:80")),
    jobs={
        "ensureadmin": Job(("ensureadmin",), "Create the operator account the config names"),
        "purge_orphaned_stores": Job(("purge_orphaned_stores",), "Delete the stored objects of data that was deleted, after the grace period"),
        "respec_datasets": Job(("respec_datasets",), "Recompute the spec of datasets created before an axis of one position stopped counting"),
        "restore_descriptors": Job(("restore_descriptors",), "Store the descriptors of every dataset and lens that misses one (--all: of every row)"),
    },
    setup=("ensureadmin", "restore_descriptors"),
)
