"""What this image answers a hub's installer: ``arkitekt-service <verb>`` (see ``arkitekt_service.contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from arkitekt_service.contract import JSON, Contract, Description, Descriptor, Facts, Hosts, Job, Needs, Offers, Scope, Signal, Start, Structure, blocks

from elektro_server.configuration import Settings
from elektro_server.vocabulary import ARRAY_DESCRIPTORS, STATED_DESCRIPTORS

#: What a token may be allowed to do here: defined at the coordination server when the hub enrols.
SCOPES = [
    Scope(key="elektro_read", description="Read electrophysiology data"),
    Scope(key="elektro_write", description="Write electrophysiology data"),
    Scope(key="elektro_analyze", description="Run analysis on recordings"),
    Scope(key="read", description="Generic read access"),
    Scope(key="write", description="Generic write access"),
]

#: The roles a member of an organization can hold here.
ROLES = [
    Scope(key="admin", description="Full administrative access"),
    Scope(key="user", description="Standard user access"),
    Scope(key="analyst", description="Can analyze recordings"),
    Scope(key="viewer", description="Read-only access"),
]

#: What an array dataset and a lens carry: what is computed from their axes, and what is only stated.
ARRAY_STRUCTURE_DESCRIPTORS = [*ARRAY_DESCRIPTORS, *STATED_DESCRIPTORS]

#: What exists on a hub because this service is there: said here, as data, so the hub knows it from
#: the image. ``service.py`` binds each of these to its model and refuses anything not said here.
HOSTS = Hosts(
    structures=[
        Structure(
            identifier="@elektro/arraydataset",
            label="Array Dataset",
            description="A multi-dimensional array dataset: a recording, a stimulus or a simulation trace, on its sample grid.",
            descriptors=ARRAY_STRUCTURE_DESCRIPTORS,
        ),
        Structure(
            identifier="@elektro/lens",
            label="Lens",
            description="A selection over an array dataset: a sweep, an epoch window, a run of channels.",
            descriptors=ARRAY_STRUCTURE_DESCRIPTORS,
        ),
        Structure(
            identifier="@elektro/tabledataset",
            label="Table Dataset",
            description="A parquet-backed table of scientific records.",
        ),
        Structure(
            identifier="@elektro/sparsedataset",
            label="Sparse Dataset",
            description="A sparse dataset, such as a spike raster.",
        ),
        Structure(
            identifier="@elektro/neuronmodel",
            label="Neuron Model",
            description="A neuron model: the cells, biophysics and topology a simulation runs.",
        ),
        Structure(
            identifier="@elektro/modelcollection",
            label="Model Collection",
            description="A named collection of neuron models.",
        ),
        Structure(
            identifier="@elektro/experiment",
            label="Experiment",
            description="Data laid out on one timeline, as layers.",
        ),
        Structure(
            identifier="@elektro/file",
            label="File",
            description="A file in its original format, as it was uploaded.",
        ),
        Structure(
            identifier="@elektro/folder",
            label="Folder",
            description="A folder: where a user files the things elektro stores.",
        ),
        Structure(
            identifier="@elektro/annotationcollection",
            label="Annotation Collection",
            description="A named set of annotations, owning the space they are drawn in.",
        ),
    ],
    signals=[
        Signal(
            identifier="@elektro/arraydataset",
            kinds=["CREATED", "UPDATED", "DELETED"],
            descriptors=[descriptor.key for descriptor in ARRAY_STRUCTURE_DESCRIPTORS],
            description="An array dataset (a recording, a simulation trace) was created, changed or deleted, with its axis counts and extents.",
        ),
        Signal(
            identifier="@elektro/tabledataset",
            kinds=["CREATED", "UPDATED", "DELETED"],
            description="A table dataset was created, changed or deleted.",
        ),
        Signal(
            identifier="@elektro/sparsedataset",
            kinds=["CREATED", "DELETED"],
            description="A sparse dataset was created or deleted.",
        ),
        Signal(
            identifier="@elektro/neuronmodel",
            kinds=["CREATED"],
            description="A neuron model was registered.",
        ),
        Signal(
            identifier="@elektro/modelcollection",
            kinds=["CREATED"],
            description="A model collection was created.",
        ),
        Signal(
            identifier="@elektro/experiment",
            kinds=["CREATED", "UPDATED", "DELETED"],
            description="An experiment was created, changed or deleted.",
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
            description="An annotation collection was created or deleted.",
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
    },
    setup=("ensureadmin",),
)
