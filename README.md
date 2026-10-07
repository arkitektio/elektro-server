# elektro-server

The electrophysiology service of an [Arkitekt](https://arkitekt.live) hub. It stores
recordings, stimuli, spike rasters and simulations as time series, together with the graph
that says when each sample was taken. It is registered as `live.arkitekt.elektro` and has a
python client, [`elektro`](https://github.com/jhnnsrs/elektro).

## What it stores

Elektro is split in two layers, and [core/DESIGN.md](core/DESIGN.md) is the document that
explains them.

**The data layer is mikro's**, vendored module for module under the same names. It knows
nothing about electrophysiology.

| Concept | What it is |
| --- | --- |
| `ArrayDataset`, `DataArray`, `Lens` | An array in a zarr store (a recording, a stimulus, waveform templates), its pyramid levels, and an immutable selection over it. |
| `TableDataset`, `SparseDataset` | Rows in a parquet store (events, trials, a sorter's units), and a sparse matrix (a spike raster). |
| `CoordinateSystem`, `Transformation` | A space is a node and a map between two spaces is an edge. A clock is a space with a time axis; a sampling law or an offset is an edge. |
| `File`, `Folder`, `AnnotationCollection` | Uploaded files, the folders data is put in, and sets of hand-drawn marks. |

**The interpretation layer is elektro's.**

| Concept | What it is |
| --- | --- |
| `Experiment`, `ExperimentLayer` | A view over a clock or a place. Each layer reads one piece of data as a trace, heatmap, waveform, spike raster, event table, series, points or annotations. An experiment names data by id and owns none of it. |
| `NeuronModel`, `ModelCollection`, `ModelWorkspace`, `ModEnvironment`, `Mechanism` | Model neurons, their collections and workspaces, and the mechanisms they are built from. |

There is no signal, segment or recording row. A recording session is a clock, a segment is
a clock with an offset onto it, and a signal is a dataset with a sampling law onto one of
them. A simulated run is its clock.

Everything belongs to an organization, and every read is scoped to the caller's.

## API

GraphQL is served at `/graphql` (HTTP and WebSocket), with the SDL at `/schema`.

| Operations | What they do |
| --- | --- |
| `request…Upload`, `finish…Upload`, `request…Access` (media, bigfile, zarr, parquet, sparse) | Hand out credentials to write to or read from the object store. Uploads are limited by role and by quota. |
| `createArrayDataset`, `createTableDataset`, `createSparseDataset`, `createLens`, `fromFileLike` | Register uploaded data. `createArrayDataset` is the one way an array enters. |
| `createSession`, `createSamplingLaw`, `createClockOffset`, `createCoordinateSystem`, `createTransformation` | Build the timing graph: clocks, and the edges that place data and other clocks on them. |
| `createExperiment`, `create{Trace,Heatmap,Waveform,Spikes,Events,Series,Point,Annotation}Layer` | Lay data out for reading. |
| `createNeuronModel`, `createModelCollection`, `createModelWorkspace`, `createModEnvironment` | Store models and what they are simulated with. |
| `createFolder`, `put…InFolder`, `linkFile`, `createAnnotation` | Organize and annotate. |
| `arrayDatasets`, `files` (subscriptions) | Updates as they happen. |

## Hub integration

Declared in [`elektro_server/contract.py`](elektro_server/contract.py):

- **Scopes**: `elektro_read`, `elektro_write`, `elektro_analyze`, `read`, `write`.
- **Roles**: `admin`, `user`, `analyst`, `viewer`.
- **Needs**: rekuest 6 or newer, an instance key, tokens issued by lok, and the storage
  kinds `media`, `zarr`, `parquet` and `bigfile`.

Elektro is known to the hub's rekuest in two separate ways:

- as a **service** (`_rekuest/service`): it hosts structures such as
  `@elektro/arraydataset`, `@elektro/experiment` and `@elektro/neuronmodel`
  ([`elektro_server/service.py`](elektro_server/service.py));
- as a **hook agent** (`_rekuest/hook`): it offers one action, `reembed_stale`
  ([`elektro_server/hook_agent.py`](elektro_server/hook_agent.py)).

The action is only offered. Nothing in this service loops or schedules; whether and when it
runs is the organization's own automation in rekuest.

## Running

The image is `jhnnsrs/elektro`. It has no default command, and starting it takes two steps:

```sh
arkitekt-service run migrate   # wait for the database, apply migrations
arkitekt-service serve                          # serve on :80 (daphne), and nothing else
```

`arkitekt-service debug` does both in one go with Django's autoreloading server, for development.

It needs Postgres with pgvector ([`jhnnsrs/daten`](https://github.com/arkitektio/daten-server)),
Redis and an S3 object store (RustFS in a standard deployment). The embedding model is baked
into the image.

## Configuration

The service reads `config.yaml`, or the file named by `ARKITEKT_CONFIG_FILE`; any value can
be overridden by an environment variable (`POSTGRES__HOST`). `python manage.py
validate_settings` prints the configuration as the service reads it, with secrets redacted.

See [CONFIG.md](CONFIG.md) for every value, including the upload roles and quotas.

## Development

```sh
uv sync
uv run pytest
```

The suite runs against a real stack, brought up by [dokker](https://github.com/jhnnsrs/dokker)
from `tests/integration/docker-compose.yaml`: Postgres (`jhnnsrs/daten:next`, override with
`DATEN_IMAGE`), RustFS with its buckets created by `jhnnsrs/init:next`, and Redis, on ports
Docker picks. It needs a running Docker daemon.

## Further reading

- [core/DESIGN.md](core/DESIGN.md): the data model, how it maps onto the old one, and where
  it differs from mikro's.
- [kanne_server/DESIGN.md](kanne_server/DESIGN.md): how quantities with units are stored.
- [docs/](docs/): the RFCs the coordinate graph follows, and the sparse store format.

`datalayer/`, `kanne_server/` and `embeddings/` are copies of the packages mikro carries.

## Releases

Releases are tags: a push to `main` cuts a stable version, a push to `next` a release
candidate. Each one publishes `jhnnsrs/elektro` under its version (`X.Y.Z`, `X.Y`, `X`),
plus `latest` from `main` and `next` from `next`. The `version` in `pyproject.toml` is a
placeholder. Release notes are on
[GitHub Releases](https://github.com/arkitektio/elektro-server/releases); `CHANGELOG.md` is
frozen.
