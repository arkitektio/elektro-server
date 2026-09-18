# Elektro's data model: mikro's data layer, an electrophysiology interpretation layer

Elektro holds time series. Until this design, every fact about *when* a sample was taken
lived in a column of whatever row happened to need it: a `sampling_rate` and a `t_start` on
an analog signal, a redundant vector of sample times beside them, a `start_time` on a
segment, an `offset` and a `duration` on every view of an experiment. Columns like these can
disagree, and did: a stimulus view and a recording view of *one* simulation could state two
different offsets, and nothing anywhere would notice that stimulus and response had been
laid out apart.

This service now uses the model mikro uses for space, for time — and it is split the way
mikro is split:

- **The data layer is mikro's**, vendored module for module at the same relative paths and
  under the same identifiers: `ArrayDataset`, `DataArray`, `Lens`, `TableDataset`, `Column`,
  `SparseDataset`, `SparseArray`, `SparseAxisReference`, `CoordinateSystem`, `Transformation`,
  `CoordinateAnchor` and its spokes, `AnnotationCollection`, `Folder`, `File`, `FileLink`, and
  the mutations that write them (`createArrayDataset`, `createTableDataset`,
  `createSparseDataset`, `createLens`, `createCoordinateSystem`, `linkFile`, …). `diff` the
  two copies of any of these files and what is left is a short, commented list. This layer
  knows nothing about electrophysiology.
- **The interpretation layer is elektro's, and it is mikro's shape.** mikro reads data as a
  *layer of a scene*; elektro reads it as a *layer of an experiment* -- a trace, a spike
  raster, an event table, hand-drawn marks. Like a scene, an experiment **names data by id and
  owns none of it**: it never creates data, and deleting it never deletes any. The one other
  interpretation is a `Simulation` (a run of a neuron model), and it is thinner still: a model,
  the integrator's parameters and a clock.

**CS first.** There is no `Block`, `BlockSegment`, `AnalogSignal`, `IrregularlySampledSignal`,
`SpikeTrain`, `Recording` or `Stimulus` any more. A recording *session* is a clock (a
coordinate system whose `epoch` is when it started), a *segment* is a clock with an offset onto
it, and a *signal* is a dataset with a timing edge onto one of them. What used to be a row per
signal is either a fact of the graph (when) or a spoke on the data (where it was recorded).

This document is the part that is elektro's own: what the concepts mean here, what was
mapped onto what, and every place the port deliberately differs.

## The ontology

Three concepts, and nothing else (mikro's [rfc9](../docs/rfc9-residence.md)):

- a **space** is a node — a `CoordinateSystem`. It owns nothing and knows nothing about
  what is in it.
- a **map** between two spaces is an edge — a `Transformation`. One row says how the two
  relate (`kind` + `params`), how well that is known (`validity`), and what a derivation did
  to the values (`value_relation`). Direction is always forward, input to output.
- **data lives in exactly one space**, and says so with a foreign key of its own.

Read for electrophysiology:

| A space is… | A map is… | Data is… |
|---|---|---|
| a **sample grid** — a dataset's axes, typed, never carrying a unit (mikro: the pixel grid) | a **sampling law** — `t = sample · period + t_start`, one affine edge (mikro: pixel size + stage position) | an **`ArrayDataset`** — a recording, a stimulus, a vector of sample times, a unit's waveform templates |
| a **level's grid** — a decimated copy's own sample indices | a **level edge** — scale and half-sample shift back into the recording's grid | a **`DataArray`** — one pyramid level; level 0 *is* the dataset's grid |
| a **clock** — one `TIME` axis in a time unit, optionally anchored to a wall-clock `epoch` | a **time lookup** — a `FIELD` whose map is the values of a times dataset | a **`Lens`** — an immutable selection over a dataset |
| a **world** — the clock an experiment is laid out on | an **offset** — where one clock sits on another | an **`AnnotationCollection`** — a set of marks, owning the space they are drawn in |
| a **drawing space** — an annotation collection's own | a **derivation** — how a computed dataset's grid maps back into its source's | a **`TableDataset`** — events, trials, a sorter's units: rows, owning the space its coordinate columns declare |
| a **raster space** — a sparse dataset's `(unit, t)` | a **key** — a FIELD whose map is an array of ids (a unit assignment) | a **`SparseDataset`** — a spike raster: units × samples, one nonzero per spike |

Four rules carry over from mikro unchanged:

1. **Edges are facts, paths are queries.** No composed map is stored anywhere. The same
   recording can sit in two experiments under two offsets, so any single stored answer
   would be wrong in one of them. Composing on read is fine (`asAffine`); storing the result
   is what is forbidden. Refine one edge and everything that looks through it moves.
2. **Store what was authored or measured; derive everything else.** A sampling rate was
   measured, so it is stored — once, on the edge. `Simulation.samplingRate` and
   `TraceLayer.duration` are *readings* of that edge. A lens' shape follows from its dataset and its slices, so it is not a column.
3. **The sample grid is structural; physical time is an interpretation.** A dataset's grid is
   always known, never wrong and never revised, which is why marks drawn over a dataset resolve against it.
   Physical time enters exactly once, as a clock plus one edge. Correcting a sampling rate
   rewrites that edge; nothing drawn in samples moves.
4. **Spaces are nodes, not strings.** `input` / `output` are foreign keys: cacheable,
   dedupable, unable to dangle.

## The data layer

`createArrayDataset(data, scales, name, axes, folder, anchors, derivedFrom, sourceFiles)` is
mikro's mutation, input for input, and it is **the one way data enters**. It writes:

- the **`ArrayDataset`** and its intrinsic coordinate system — the sample grid, whose axes
  are checked against the rank and the `dimension_names` of the zarr itself
  (`assert_axes_describe_the_store`), and whose structural `spec` is materialized once
  (`[SCALAR, TIMESERIES, MULTICHANNEL]` for a `(t, c)` recording);
- one **`DataArray`** per pyramid level. The store belongs to the *level*, not the dataset.
  Level 0 lives in the dataset's own grid; every `scales` entry gets a grid of its own and a
  stored edge into level 0's, its factor derived from the actual shapes. For ephys this is
  the decimated overview a client reads when zoomed out over an hour at 30 kHz. A pyramid
  over an `INDEX` axis or a `CATEGORIZED` derivation may only be built by `NEAREST` or
  `MODE` — averaging sorted-unit ids or event codes invents values;
- the **derivation edges** (`derivedFrom`) and the **file links** (`sourceFiles`);
- the **anchors**: a `CoordinateAnchor` pins *spokes* to coordinates of the dataset —
  `{}` for the whole dataset, `{c: 3}` for a channel, `{sweep: 12}` for a sweep.

| Spoke | Says | mikro's counterpart |
|---|---|---|
| `ValueUnit` | what the **values** measure (`mV`, `pA`, `second` for a times dataset) | — (a pixel has no unit) |
| `ChannelLabel` | what a channel, sweep or unit is called | the same |
| `RigState` | the hardware truth, typed by [`rigkit`](../rigkit/): clamp mode, holding level, series resistance, membrane capacitance, temperature, then per-device named settings | `OptikitState` / `optikit` |
| `ValueHistogram` | the distribution of values, for a display range without reading the array | the same |
| `AcquisitionMetadata` | whatever the source format said, as a JSON object | `OmeMetadata` |

Everything that says where the data *is* is written at creation and never after: only
`name` and `description` are editable (`updateArrayDataset`, audited). A recomputation is a
new dataset, derived from the old one.

Three things are elektro's own inside this layer, each marked where it happens:
`createArrayDataset` is **one transaction** (a refusal takes the dataset with it), anchors
are **checked against the axes** (`{ch: 3}` on a `(t, c)` dataset would otherwise be a label
that labels nothing), and `deleteArrayDataset` / `deleteDataArray` / `deleteLens` **sweep the
spaces they leave empty**.

### Tables and sparse matrices

`createTableDataset(data, columns, name, folder, derivedFrom, sourceFiles)` and
`createSparseDataset(store, axes, name, folder, derivedFrom, sourceFiles)` are mikro's, input
for input (`tests/test_print_schema.py` pins the field sets against a snapshot of mikro's --
refresh it when re-vendoring, as its comment says), over the same
stores: a `ParquetStore` whose schema `finishParquetUpload` reads off the file, and a
`SparseStore` -- a sporadik prefix of anndata-spelled CSR/CSC layouts -- whose spec, shape and
layouts `finishSparseUpload` reads off the block. Each owns its coordinate system, as a
collection does, and is a registered container (`graph.CONTAINERS`), so it is a `Resident`, a
member of `InViewSource`, a derivation source and a node of `lineageGraph`.

Read for electrophysiology:

| Thing | Stored as | Its space |
|---|---|---|
| **events / epochs** (TTL edges, trials, Neo `Event`/`Epoch`) | a table with one TIME coordinate column (and a stop column for an interval) | `(t)`, in the column's unit, placed on a clock by an offset |
| **units** (a sorter's cluster table) | a table with one INDEX coordinate column (`unit_id`) and attribute columns (depth, channel, quality) | `(unit_id)`, placed by nothing -- it is looked up |
| **spikes** | a sparse dataset over `(unit: INDEX, t: TIME)`, `unit` identified by the units table | `(unit, t)`, placed on a clock by a **sampling law** over `t` |
| **waveform templates** | an array dataset `(unit, c, w)`, derived from the raster (UNMAPPABLE) | its own grid |

`identifiedBy` on a column or a sparse axis says what its values **are**: a `DATASET` whose
contents are the ids (a FIELD edge into this space -- a per-sample unit assignment keying the
raster's units) or a `TABLE` whose rows they are (a foreign key, `Column.references` /
`SparseAxisReference`, which authors no edge). mikro's `MESH_COLLECTION`, `NETWORK_COLLECTION`
and `NETWORK_COLLECTION_NODES` have nothing to name here and are gone (divergence 14).

**The one additive divergence: a sparse axis may be TIME** (divergence 15). mikro's sparse axes
all enumerate, so its `SparseAxisInput` has no `type`. A raster's sample axis has a metric -- it
was sampled exactly as the recording it was sorted from -- so `type` exists here, defaults to
INDEX (a mikro client that never sends it is unaffected), admits INDEX and TIME, and at most one
TIME. A TIME axis is identified by nothing (`identifiedBy` must be empty, and so defaults to
`[]`): its positions are samples, and a sampling law onto a clock says when they were. For a
FIELD keying the raster's *units* the TIME axis is **optional** (`graph.self_placed_axes`): a
per-sample assignment passes it through by name, a per-channel one does not mention it, and
neither is refused -- but it is never *produced*, because an instant is not an id.

Deleting a table or a sparse dataset sweeps the space it owned (divergence 7), taking every
edge touching it -- a sampling law, an offset, a key -- and flags its store. A table another
column references, or one a layer's picker names, is refused (`core/logic/pickers.py`).

**Filing** is mikro's too: `Dataset` became **`Folder`** (the old name collided with the data
it filed), its foreign keys are `SET_NULL` — deleting a folder *unfiles*, where the old
`Dataset` cascaded into every file in it — and derived data follows its primary parent
(`core/logic/folder.py`). The four fileable containers are an array dataset, a table dataset,
an annotation collection and a sparse dataset. A **`FileLink`** relates a file's bytes to a
container, from either end (`sourceFiles`, `exportOf`, `linkFile`), and is deliberately not a
derivation: a file has no space. A sparse dataset is a link container here and not in mikro
(a raster is read out of a sorter's output folder as surely as an array out of an ABF).

**Stores outlive their data.** No delete mutation touches S3. A delete flags the stores it
leaves unreferenced (`orphaned_at`), and `manage.py purge_orphaned_stores` collects them
after `DATALAYER_STORE_GRACE_DAYS`, re-checking for referrers first (`core/logic/storage.py`).

## The interpretation layer

| mikro | elektro |
|---|---|
| `Scene` over a `world` | `Experiment` over a `world` |
| `Layer`, one table discriminated by `kind`, exactly one source | `ExperimentLayer`, one table discriminated by `kind`, exactly one source |
| image / intensity / label … over a `Lens` | `TRACE` over a `Lens` (any array dataset: a recording, a stimulus, any signal) |
| point / track over a `TableDataset` | `EVENTS` over a `TableDataset` with a TIME column |
| *(no sparse layer: a matrix only colours)* | `SPIKES` over a `SparseDataset` with a TIME axis |
| annotation over an `AnnotationCollection` | `ANNOTATION` over an `AnnotationCollection` |
| `createScene`, `createSceneFromCoordinateSystem`, `createXxxLayer` / `updateXxxLayer`, `createLayer` / `updateLayer` / `deleteLayer` | `createExperiment`, `createExperimentFromCoordinateSystem`, `create{Trace,Spikes,Events,Annotation}Layer` / `update{Trace,Spikes,Events}Layer`, `createLayer` / `updateLayer` / `deleteLayer` |

A layer carries **view state only**: compositing (`blending`, `opacity`, `visible`, `order`,
`name`) and its kind's render settings (a trace's channel and value range; a raster's tick
height, row order and rate bin; an event table's stop, label and lane columns; the colour and
filter pickers). Where its data sits is the graph's answer -- `pathToWorld`, `asAffine`,
`placement`, `placementValidity`, `placementInvariance`, read from
`graph.layer_source_system(layer)` to the world, exactly as mikro reads a layer -- and nothing
about time is a column of it. A spikes or events layer has no lens and shows its whole dataset:
windowing it is the viewer's business, not a second selection vocabulary on the server.

**Pickers are mikro's COLUMN entries**, stored in the same JSON shape (`core/render/pickers.py`):
a table, a column, a `joinPath` of `Column.references` hops, a colormap and its window. An
events layer's rows are its table's rows; a spikes layer's units are the rows of the table
identifying its unit axis (`SpikesLayer.unitTable`). A categorical column takes a qualitative
colormap, a measure a continuous one, checked at the boundary (`core/logic/ephys_pickers.py`).

**CS first.** A session is built as mikro builds a staging: spaces and edges first, then the
composition read off them.

1. `createCoordinateSystem` -- the session clock, one TIME axis, `epoch` = when it started;
2. `createArrayDataset` / `createTableDataset` / `createSparseDataset` -- the data;
3. `createSamplingLaw` for every regularly sampled dataset *and* every raster, a FIELD
   `createTransformation` for an irregularly sampled one, `createClockOffset` for a segment's
   clock onto the session's, or an event table's space onto either;
4. `createExperimentFromCoordinateSystem(session clock)` -- a layer for everything that reaches
   the clock (`core/logic/experiment.py`, mikro's `bootstrap_scene_from_system`): TRACE for an
   array dataset with a TIME axis (never a times dataset -- that is a lookup's map), SPIKES for
   a raster, EVENTS for a table with a TIME column, ANNOTATION for a collection. It authors no
   edges; `skipUnplaceable` leaves out what does not reach rather than refusing.

`createSamplingLaw` and `createClockOffset` are the only elektro-only timing mutations, and they
write nothing `createTransformation` could not: they exist because a rate and a start arrive as
kanne quantities and the edge wants float64 numbers in the *clock's* unit, a period rather than
a rate. Both refuse a rival -- a second law of one grid onto one clock, a second offset of one
clock onto another -- because two edges between the same two spaces are rivals the path search
chooses between, not a correction (`clocks.TimedOnce`).

There is **no `offset` on a layer**, and no longer one on anything but the edge. It used to be a
column on every view, and a stimulus view and a recording view of one run could state two
offsets and silently misalign stimulus and response. An offset is a fact about a clock, shared
by everything timed on it, and stated once. `createTraceLayer` keeps one piece of input sugar,
`window`: a stretch of time on the dataset's own clock, lowered to a lens by inverting its
sampling law (refused over a lookup, which has no closed-form inverse; a dataset timed on two
clocks needs the `clock` named).

**A simulation** is a run of a neuron model: `model`, the integrator's `dt` and `duration`, and a
`clock`. What was recorded where is **not** a row of it: it is a `RecordingSite` or
`StimulusSite` spoke on the dataset's own anchor (`{}` for the dataset, `{c: i}` per channel),
beside the rig state, written by `createArrayDataset` -- a site is a fact of the measurement,
not of the run, and the data layer does not point at the interpretation layer.
`createSimulation(datasets, sampling | timeDataset)` writes the clock and one timing edge per
named dataset; with no datasets it mints the clock alone, and datasets are timed on it later,
one `createSamplingLaw` at a time. `Simulation.datasets` / `.recordings` / `.stimuli` are read
off the graph: the datasets with a timing edge onto its clock, and among them those whose
anchors carry the matching spoke.

Deleting an interpretation deletes the interpretation. `deleteExperiment` and `deleteLayer`
leave every dataset where it was; `deleteSimulation` sweeps its clock once nothing is laid out on
it, which takes the timing edges onto it along. The other direction cascades: deleting a dataset
takes the layers that drew it, because a layer of data that no longer exists is a layer of nothing.

## What was mapped onto what

Two passes. The first turned every time column into an edge; the second turned every row that
*named* a dataset -- a signal, a recording, a view -- into a layer, a spoke, or nothing.

| Was | Is now |
|---|---|
| `AnalogSignal` (+ `.sampling_rate`, `.t_start`) | an `ArrayDataset` and its **sampling law** (one `BY_DIMENSION` edge, grid → clock, `createSamplingLaw`); drawn as a TRACE layer |
| `IrregularlySampledSignal` (+ `.time_trace`) | an `ArrayDataset` and a **time lookup** (a FIELD edge whose field is a times dataset); drawn as a TRACE layer |
| `SpikeTrain` (one unit's spike times, `t_start` / `t_stop`, `waveforms`) | one row of a **spike raster**: a `SparseDataset` over `(unit, t)`, its `t` placed by a sampling law, its `unit` identified by a units table; drawn as a SPIKES layer. The observation window is the raster's extent along `t`; templates are an `ArrayDataset (unit, c, w)` derived from the raster |
| Neo `Event` / `Epoch` (were annotations on a segment clock) | a `TableDataset` with a TIME column (and a stop column for an epoch), placed on the clock by an offset; drawn as an EVENTS layer. Annotations remain for hand-drawn marks |
| `Block` (+ `.recording_time`, `.clock`, `.folder`, `.origin`) | a session **clock** -- a `CoordinateSystem` whose `epoch` is the recording time -- plus the datasets timed on it, filed in a `Folder` and linked to their file by `sourceFiles` |
| `BlockSegment` (+ `.start_time`) | a segment clock and an offset edge onto the session clock (`createClockOffset`) |
| `BlockGroup` | gone: a channel group is `ChannelLabel` anchors; a unit group is a column of the units table |
| `Recording` / `Stimulus` rows (`cell`, `location`, `position`, `kind`) | a `RecordingSite` / `StimulusSite` **spoke** on the dataset's anchor |
| `Simulation.time_trace` | the field of the run's time lookups (`timeDataset`) — or absent, when the run has sampling laws |
| `Experiment.time_trace` | `Experiment.world`, a space it adopts and never owns |
| `ExperimentRecordingView` / `ExperimentStimulusView` / `ExperimentAnnotationView` | one `ExperimentLayer` table, kinds TRACE / SPIKES / EVENTS / ANNOTATION |
| `…View.offset` | **one** offset edge per clock → world (`createClockOffset`), shared by every layer over that clock |
| `…View.duration` | `TraceLayer.duration`: the lens' extent over the sampling law's rate |
| `AnalogSignal.unit`, `AnalogSignalChannel.unit`, `SpikeTrain.unit` | a `ValueUnit` anchor on the dataset (`{}`, or `{c: i}` per channel) |
| `AnalogSignalChannel` (`index`, `name`) | a `ChannelLabel` anchor at `{c: index}` |
| `Trace` (one store) | `ArrayDataset` + a `DataArray` per level |
| `Trace.kind` | derived: the dimensionality of the value unit (`valueDimension`) |
| `Trace.tags`, `.pinned_by` | gone, as in mikro: file it in a `Folder` |
| `Dataset` | `Folder` |
| abstract `View` (`a_min…c_max`), `TimelineView`, `ViewCollection` | `Lens` |
| `FileView` | `FileLink` — a link to a file is not a selection over a dataset |
| `ROI` (`trace` FK, `min_t` / `max_t` in samples, kinds `LINE` `POINT` `SPIKE` `SLICE`) | `Annotation` in an `AnnotationCollection` — see below |

What a client used to read off a signal row is read off the graph now: a dataset's rate on a
clock is its sampling law (`Transformation.affine`, or `TraceLayer.duration` for the shown
stretch); a run's `samplingRate` and `timeDataset` are derived from its edges, as before.

### Why one edge and not two

A sampling law is *one* `BY_DIMENSION` edge, never a `SCALE` edge beside a `TRANSLATION`
edge. Two edges between the same two spaces are **rivals** the path search chooses between
(rfc9), not a composition it multiplies. And it is a `BY_DIMENSION` even for a one-axis
dataset, so a `(t)` and a `(t, c)` dataset read identically, and because it is the honest
statement for the second: the law says *nothing* about `c`, where a rank-changing `AFFINE`
would say "times zero".

### Axis types

`SPACE`, `TIME`, `CHANNEL`, `INDEX`, `COORDINATE`, `DISPLACEMENT`, and two that are new:
`FREQUENCY` (its unit must measure `1 / [time]`) and `VALUE` (the y axis of a plotted signal;
only a drawing space has one — see Annotations). mikro's `MICROTIME` and `SPECTRUM` name
optical acquisitions and are gone.

The sample axis of a signal is **`TIME` with no unit, never `INDEX`** — even when sampling is
irregular, the way a timelapse frame index is `TIME` in mikro. An `INDEX` axis has no
metric, so the graph refuses any `SCALE` / `TRANSLATION` / `AFFINE` over it, and a sampling
law could not be stated. `INDEX` is for what genuinely has none: a sweep, a trial, a unit.
A spike raster's sample axis is TIME for the same reason a recording's is -- it is placed by
a sampling law -- and its unit axis is INDEX.

### Annotations

An `ROI` hung off one trace by a foreign key and kept its extent in two integer columns of
sample indices, so it could mark one array and nothing else, in one unit and no other. It
is replaced by mikro's annotation model (`core/models/annotation.py`, vendored): an
`Annotation` belongs to an `AnnotationCollection`, the collection **owns the coordinate
system its shapes are drawn in**, and what that space is related to — by an edge, never by
a second FK on the shape — decides what the marks mean:

- drawn over a **dataset's sample grid**, a collection marks that dataset, in samples;
- drawn on a **segment's clock**, it marks *every dataset timed on the clock at once*, in the
  clock's unit;
- drawn on an **experiment's world**, it marks the timeline and everything laid out on it.
  `createAnnotation(experiment:)` is the sugar for this: the first mark mints the
  experiment's collection — a space copying the world's axes, an identity edge into the
  world, and one ANNOTATION layer — and later marks append to it. Deleting the experiment
  keeps what was drawn; only the layer cascades.

Annotations are **hand-drawn marks**: an artifact someone flagged, a measurement drawn on a
trace. Events and epochs that arrive in bulk -- a TTL channel's edges, a trial table, Neo's
`Event` and `Epoch` read out of a file -- are rows, and rows are a `TableDataset` with a TIME
column, drawn as an EVENTS layer. The two are different facts (a person's judgement, an
acquisition's record) and keep different homes.

A collection is a registered container (`graph.CONTAINERS`, `is_collection=True`), so it is
a `Resident`, a derivation source, something that can be registered into a space, and a
node of `lineageGraph`. `CoordinateSystem.annotations` answers by *reachability*: asked of a
clock, it returns the marks drawn on the clock and those drawn over any dataset sampled onto it.

**Kinds name geometry only** (mikro's rule), in Neo's vocabulary where Neo has one:
`EVENT` (one instant), `EVENTS` (several), `EPOCH` (two opposite corners — an interval in a
`(t)` space; the same two corners also bound a run of channels in `(t, c)` or a range of
values in `(t, v)`), `LINE`, `PATH`, `POLYGON`. What a mark *means* — a spike, an artifact —
is its name and its collection; the old `RoiKind` mixed the two (`SPIKE` beside `LINE`) and
so could not say "an epoch that is an artifact".

The **`VALUE` axis type** exists for drawing spaces: a line from baseline to peak is drawn
in `(t, v)`. A dataset's own sample grid never has one — what was measured at a sample is
not a coordinate of it — and an edge between a drawing space and a grid names `t` and says
nothing about `v`.

An annotation's bounding box is stored twice, as in mikro: as JSON (`intrinsicBbox`, what
the API reads) and as a Postgres `cube` (GiST-indexed, what `intersects`, `containsPoint`
and `nearestAnnotations` search). Boxes compare only within one frame, so those filters
require a `collection` or `coordinateSystem` alongside. The box is re-derived whenever the
vectors change — the ROI's `min_t` / `max_t` were written at creation only.

### Value units are not axes

An axis says *where* a sample is. What was measured there — mV, pA — is a **`ValueUnit`
spoke on an anchor**, validated as a pint unit. Not a column, for two reasons: it may differ
along an axis (a `(t, c)` recording whose channels are a membrane potential and a command
current has two, at `{c: 0}` and `{c: 1}`), and it keeps `createArrayDataset` identical to
mikro's. `ArrayDataset.valueUnit` reads the dataset-wide anchor, the one pinned to no
coordinate; `valueDimension` is derived from it. Per-channel gain and offset are value
calibration and never a coordinate edge. The one place a value unit meets the graph is a
times dataset: its values *are* coordinates, so a time lookup requires its dataset-wide
value unit to be the clock's unit (see below).

### What stays a quantity column, and why

kanne's canonical integers (picoseconds, nanohertz) remain the wire and column format.
Two things stay columns although they are about time:

- `Simulation.dt` and `.duration` are the **integrator's** parameters (NEURON's `h.dt`,
  `h.tstop`). A run can record at a coarser interval than it integrates, so `dt` is not the
  sampling period and must not be read as one. `dt` is nullable: its old default was one
  *second*.
- *(`SpikeTrain.t_start` / `.t_stop`, the observation window, went with the spike train: a
  raster's window is its extent along `t`, which a zero column cannot shrink -- no spikes
  over ten seconds and no spikes over a hundred are two rasters of different shape.)*

Numbers *on an edge* are float64 in the output clock's unit. float64 seconds are exact to
the picosecond for about 2.5 hours and good to ~15 ps over a day. `rate → period → rate`
round-trips exactly through nanohertz up to roughly 100 kHz and drifts in the last digit
near 1 MHz; read the edge's `affine` when that matters.

## Residence rules

From "data lives in exactly one space":

- **R1.** Every dataset owns its sample grid: `createArrayDataset` mints one, as in mikro.
  Residence still *allows* several datasets in one frame (the FK is not one-to-one), and the
  graph handles it; nothing in this service writes it.
- **R3.** A dataset whose *values are a map* — a times dataset, the `field` of a `FIELD`
  edge — lives alone in its system. Enforced where the edge is written
  (`graph.assert_field_is_dereferenceable`).

There is no R2 any more. An earlier revision put every recording and stimulus of one
simulation into **one shared grid**, timed by one edge. That made "these were sampled
together" a fact about residence, which mikro's writers never produce and its readers never
expect — and it meant a simulation had to *create* its arrays to control where they lived.
A run now writes one timing edge per dataset, all onto its one clock; that stimulus and
response line up is a fact about those edges, and correcting one is correcting one.

Layers and site spokes are **not** residents. A layer names data and a spoke describes it;
making either a container would give one dataset two homes. Tables and sparse datasets *are*
residents -- each lives in the space it owns (R1, as a collection does).

## Where this port differs from mikro

Each of these is deliberate, and each is marked where it happens in the code.

1. **Chains of frames** (`graph.frames_into`). mikro roots every search at one space and
   fetches the edges touching *it*, plus the facts of whatever data registers into it
   directly. Here the ordinary layout is a chain — sample grid → segment clock → session
   clock → world — and every hop but the first is an edge between two spaces nothing lives
   in, which belongs to no dataset's facts and does not touch the world. mikro's fetch never
   sees it, so a recording laid out through its clock was invisible to `inView` and every
   `placeableIn` picker, and unplaceable past two hops. A search therefore also owns the
   frames chained *into* its root — backwards only, so a session clock shared by two
   experiments does not leak one's layout into the other.
2. **Layers over lookup-timed data are admitted.** mikro's [rfc10](../docs/rfc10-affine-placement-gate.md)
   refuses a layer whose route does not condense into one affine map. An
   irregular signal and a variable-step simulation all reach time across a `FIELD`, which
   never condenses, and a timeline can draw them without a matrix. Every layer create and
   rebind gates on *reachability* (`core/logic/experiment.py::assert_reaches`); such a layer
   reports `placement: PLACED`,
   `placementInvariance: DIFFEOMORPHIC`, and `asAffine` errors, naming the edge that stopped
   it. The `placeableIn` **filters** and `placedSystems` stay strict, as in mikro: they
   answer "what can be laid out with one map". `inView` is not a picker -- it answers "what is
   in this space" -- so it lists such a source too, with `extentState: NON_AFFINE`, its path,
   and no box; seeded from the strict set it used to leave a recording out of its own clock.
3. **R3**, above. mikro asks only that *something* live in a field's system.
4. **A lookup checks units.** A `FIELD` states no numbers, so it has nothing to convert
   with; times in milliseconds read against a clock in seconds would put every sample a
   thousandfold early and nothing downstream could tell. Refused at write time.
5. **Everything is tenant-scoped.** mikro leaves `coordinateSystems` and `transformations`
   unscoped; every type here mixes in `OrgScoped` and every id a client sends goes through
   `scoping.get_for_org`.
6. **`WORLD_RELATIONS`.** mikro has one kind of composition (`scenes`) and spells it inline.
   Two things are laid out over a space here — an experiment over its world, a simulation over
   its clock — so it is a registry, read by the delete guard, the orphan sweep and
   `sweep_empty_systems`. `tests/test_architecture.py` derives it from the foreign keys, so
   a fifth composition is a failing test rather than a clock swept out from under it.
7. **A space leaves with what it was for.** Nothing owns a space, and a dataset's FK to its
   grid is `PROTECT`, so neither can cascade. `deleteArrayDataset`, `deleteDataArray`,
   `deleteLens`, `deleteTableDataset` and `deleteSparseDataset` delete the data and then sweep
   the spaces left empty (`_generic.make_owned_space_delete` for the last two);
   `deleteSimulation` sweeps the *clock* left empty (`spaces.sweep_empty_systems`). mikro
   leaves both to an orphan sweep. A *world* is never swept by deleting what was laid out
   over it.
8. **Filters state what `null` means.** This service runs strawberry-django with
   `USE_DEPRECATED_FILTERS`, where an explicit `null` reaches a filter resolver. mikro's
   `uninhabited` is `condition if value else ~condition`, which would read `null` as `false`.
9. **The optimizer's `only` pruning is off**, as in mikro: it drops `Transformation.kind`,
   the column every concrete transformation type is discriminated by.

10. **Half a cell, or nothing.** mikro pads every annotation vertex by half a voxel — right
    when a vertex names a cell of a grid (sample 340 covers `[339.5, 340.5)`), wrong when it
    is an instant on a clock: an event at 12.5 s padded to `[12.0 s, 13.0 s)` would answer
    range queries half a second off. `graph.vertex_padding` reads what the collection is
    drawn over: a sample grid pads by half a sample, a unit-carrying space by nothing.
11. **Nested relations keep their prefetch.** Scoping `Axis` and `Transformation` like
    every other type re-filtered relations `coordinateGraph` had already prefetched — a
    query per system. `OrgScopedOrNested` scopes root reads and leaves the relation of an
    already-scoped parent alone. (Found by mikro's ported query-count test.)

12. **The data layer's additions**, listed under "The data layer" above: an atomic
    `createArrayDataset`, anchors checked against the axes, a `ValueUnit` spoke, and the
    `RecordingSite` / `StimulusSite` spokes (one per anchor, never both). And one
    substitution: `rigkit` for `optikit`, `AcquisitionMetadata` for `OmeMetadata`.
13. **One delete predicate.** mikro passes an `owner` callable per model; this service has
    `core/guards.py` (`ANCHOR_PATHS`), so `core/mutations/_generic.py::make_delete` takes no
    `owner`. The store straddle — collect, delete, flag — is mikro's.
14. **Two ways to identify an axis, not five.** `IdentificationKind` is `DATASET` and `TABLE`:
    mikro's `MESH_COLLECTION`, `NETWORK_COLLECTION` and `NETWORK_COLLECTION_NODES` name
    collections this service does not have, and `Column.nodeReferences` went with them
    (`core/inputs/identification.py`, `core/logic/identification.py`, which returns two
    things rather than three). `tests/test_print_schema.py` pins every other field against mikro's.
15. **A sparse axis may be TIME** (`core/inputs/sparse.py`, `core/mutations/sparse_dataset.py`,
    `graph.self_placed_axes`) -- see "Tables and sparse matrices". The one additive field of the
    port; `identifiedBy` defaults to `[]` so a TIME axis can omit it. `identified_axes` is
    mikro's, unchanged: the raster's TIME axis is *optional* for a keying FIELD, which is a
    different rule from *identified* (an identified axis may not be named by the edge at all).
16. **A layer's source is a database constraint** (`experiment_layer_has_the_source_its_kind_names`).
    mikro checks "exactly one source, the one the kind draws" in its mutations only. And a
    SPIKES kind exists where mikro deliberately has no sparse layer (a mikro matrix only
    colours): here a raster *is* the thing drawn, a tick per nonzero. Layers default to
    NORMAL blending, not ADDITIVE: a trace is a line in a lane, and summing two voltages'
    pixels means nothing.
17. **Pickers are COLUMN-only**, and their validation is a table walk, not a FIELD walk
    (`core/logic/ephys_pickers.py`). An events layer's rows are its table's rows and a spikes
    layer's units are its unit table's, so no picker crosses an edge -- which is why mikro's
    `assert_edge_not_stranding_a_picker`, `attributePlans` and the options queries have no
    counterpart. The stored JSON is mikro's COLUMN entry, field for field.
18. **A sparse dataset is a file-link container.** mikro's `write_file_links` refuses one.
19. **Two timing mutations**, `createSamplingLaw` and `createClockOffset`, which write nothing
    `createTransformation` could not (see "The interpretation layer"), and
    `createExperimentFromCoordinateSystem` seeds from the loose reachable set (divergences 1
    and 2) rather than mikro's one-hop scan, so a raster timed on a segment clock chained
    into a session clock is staged over the session.

One thing was ported **verbatim although it looks wrong**: `_assert_epochs_agree` refuses
*every* edge between two clocks anchored to different instants — `TRANSLATION` included —
while its own error message says "state the offset as a TRANSLATION". In electrophysiology
two anchored clocks related by an offset is the ordinary synchronisation problem (a probe's
clock against a DAQ's). The rule is unchanged here so the two copies stay comparable; the
consequence is that an experiment's world has no epoch by default, and that two anchored
clocks cannot currently be synchronised by an edge. Fix it in mikro first.

## What the API looks like

Two steps, as in mikro: data first, then what it means.

```graphql
mutation {
  createArrayDataset(input: {
    data: "<zarr store>", name: "probe A",
    axes: [{name: "t", type: TIME}, {name: "c", type: CHANNEL}],
    scales: [{level: 1, array: "<decimated store>", scaleMethod: MAX}],
    anchors: [
      {axisAnchors: [], valueUnit: {unit: "uV"},
       rig: {mode: CURRENT_CLAMP, holdingCurrent: "0 pA", temperature: "32 degC"}},
      {axisAnchors: [{axis: "c", value: 0}], label: {label: "CA1 pyr"}}
    ],
    sourceFiles: [{file: "12", seriesIdentifier: "sweep-3"}]
  }) { id valueUnit spec intrinsicSystem { id } dataArrays { level shape toParent { kind } } }
}
```

A session, CS-first -- a clock, the data timed on it, then the experiment read off it:

```graphql
mutation {
  session: createCoordinateSystem(input: { name: "session 12", epoch: "2026-09-17T09:00:00Z",
    axes: [{name: "t", type: TIME, unit: "second"}] }) { id }
}
# ... createArrayDataset (the recording, above), createTableDataset (units: unit_id INDEX, depth, quality;
#     events: t TIME in seconds, stop, label), then the raster over the sorter's output:
mutation {
  createSparseDataset(input: { name: "sorted spikes", store: "<sporadik store>",
    axes: [{name: "unit", identifiedBy: [{kind: TABLE, table: "<units>"}]}, {name: "t", type: TIME}] }) { id coordinateSystem { id } }
}
mutation {
  a: createSamplingLaw(input: { source: "<recording grid>", clock: "<session>", samplingRate: "30 kHz", tStart: "2 s" }) { id }
  b: createSamplingLaw(input: { source: "<raster space>",   clock: "<session>", samplingRate: "30 kHz", tStart: "2 s" }) { id }
  c: createClockOffset(input: { clock: "<events space>", onto: "<session>", offset: "0 s" }) { id }
}
mutation {
  createExperimentFromCoordinateSystem(input: { coordinateSystem: "<session>" }) {
    layers {
      kind placement placementInvariance pathToWorld { transformation { kind } }
      ... on TraceLayer   { lens { dataset { name valueUnit } } duration }
      ... on SpikesLayer  { sparseDataset { name } unitTable { name } }
      ... on EventsLayer  { tableDataset { name } timeColumn stopColumn }
    }
  }
}
```

A layer by hand, over a world of its own:

```graphql
mutation {
  experiment: createExperiment(input: { name: "paired pulse" }) { id world { id } }
}
mutation {
  createClockOffset(input: { clock: "<run clock>", onto: "<world>", offset: "50 ms" }) { id }   # ONE edge, shared by every layer of the run
  createTraceLayer(input: { experiment: "<experiment>", dataset: "7", window: { start: "0 ms", stop: "200 ms" }, channelIndex: 0 }) {
    placement placementValidity asAffine { matrix } duration lens { slices { axis start stop } }
  }
  createSpikesLayer(input: { experiment: "<experiment>", sparseDataset: "3", rowOrderColumn: "depth",
    colorBys: [{ table: "<units>", column: "quality", colormap: HUES }], activeColorBy: 0 }) { id }
}
```

`window` is *input sugar*, lowered once to a lens in sample indices by inverting the sampling
law (refused over a lookup, which has no closed-form inverse — cut a lens in samples with
`createLens` instead). There is no `offset` sugar: an offset is `createClockOffset`, once per clock.

## Migrations

The initial migration was **regenerated** (as mikro did). A data migration would have had to
re-implement edge derivation against historical models — a second copy of the logic this
design forbids — and could never be tested, because the test settings disable migrations.
It creates the Postgres `cube` extension first (hand-added, as in mikro: `makemigrations`
cannot emit it), so the database role needs the right to `CREATE EXTENSION`.
Deploying this requires resetting the elektro database; stores whose rows are dropped become
orphaned objects in S3. The datalayer app gained two ordinary migrations
(`0002_datalayerstore_orphaned_at`, `0003_sparsestore_parquetstore_columns`), and the core
migration was regenerated once more for layers, tables, sparse datasets and site spokes --
another reset. `tests/test_architecture.py` checks that the models and the
migration agree, and that the migration actually runs on an empty Postgres.

## Breaking changes for API clients

**Layers, tables and sparse datasets** (the second pass):

- **Removed:** `Block`, `BlockSegment`, `BlockGroup`, `AnalogSignal`,
  `IrregularlySampledSignal`, `SpikeTrain`, `Recording`, `Stimulus` -- types, queries
  (`blocks`, `block`, `blockStats`, `analogSignals`, `analogSignal`, `recordings`,
  `recording`, `stimuli`, `stimulus`), `createBlock` and every `delete*` of them,
  `put/releaseBlocks{In,From}Folder`, `File.blocks`, `Folder.blocks`, the `Block` member of
  `FolderChild`, and `ArrayDataset.analogSignals` / `.irregularlySampledSignals` /
  `.spikeTrains` / `.recordings` / `.stimuli` (→ `ArrayDataset.experimentLayers`,
  `.simulations`, and the site spokes on `anchors`).
- **Experiment views → layers:** `ExperimentView`, `ExperimentLensView`,
  `ExperimentRecordingView`, `ExperimentStimulusView`, `ExperimentAnnotationView` and their
  deletes → the `ExperimentLayer` interface (`TraceLayer`, `SpikesLayer`, `EventsLayer`,
  `AnnotationLayer`), `Experiment.layers`, `layers` / `layer` queries, `createLayer`,
  `updateLayer`, `deleteLayer`, `create{Trace,Spikes,Events,Annotation}Layer`,
  `update{Trace,Spikes,Events}Layer`. `AnnotationCollection.experimentViews` →
  `experimentLayers`. A view's `label` is a layer's `name`; `offset` is gone from every layer
  (→ `createClockOffset`); `duration` is `TraceLayer.duration`.
- **`createExperiment`** takes `coordinateSystem` (was `world`), `axes` and `epoch`, and no
  views; new `createExperimentFromCoordinateSystem` and `updateExperiment`.
- **`createSimulation`** takes `datasets: [ID]` (was `recordings` / `stimuli` with sites);
  sites are `anchors: [{recordingSite: {...}}]` / `{stimulusSite: {...}}` on
  `createArrayDataset`; `sampling` / `timeDataset` are required only with `datasets`.
  `Simulation.recordings` / `.stimuli` return `ArrayDataset`s; new `Simulation.datasets`.
- **New:** `createTableDataset` / `updateTableDataset` / `deleteTableDataset`,
  `createSparseDataset` / `updateSparseDataset` / `deleteSparseDataset`, the sparse store's
  `request/finish/refreshSparseUpload` and `request(General)SparseAccess`, `tableDatasets` /
  `sparseDatasets` queries, `put/release{Table,Sparse}Datasets{In,From}Folder`,
  `createSamplingLaw`, `createClockOffset`; `TABLE_DATASET` / `SPARSE_DATASET` file-link
  containers; `TABLE_DATASET` derivation source; `Resident` and `InViewSource` gain
  `TableDataset` and `SparseDataset`. The enums `ColorMap` and `Blending` are back (mikro's).

**The first pass** (time columns → edges):

- **The data layer is mikro's, by name.** `Trace` → `ArrayDataset` (+ `DataArray` levels);
  `fromTraceLike` → `createArrayDataset` with mikro's input (`data`, `scales`, `name`,
  `axes` — **always required**, `folder`, `anchors`, `derivedFrom`, `sourceFiles`);
  `updateTrace` / `deleteTrace` → `updateArrayDataset` / `deleteArrayDataset`; new
  `deleteDataArray`; queries `traces` / `trace` → `arrayDatasets` / `arrayDataset`; scalar
  `TraceLike` → `ArrayLike`; `DerivationSourceKind.TRACE` → `DATASET`; every `trace:` field
  and argument → `dataset:`; subscription `traces(dataset:)` → `arrayDatasets(folder:)`.
  `pinTrace`, `randomTrace`, `Trace.tags` and `Trace.pinned` are removed.
- **`Dataset` → `Folder`**: `createDataset` … → `createFolder`, `ensureFolder`,
  `updateFolder`, `revertFolder`, `pinFolder`, `deleteFolder`,
  `put/release{Folders,Files,ArrayDatasets,AnnotationCollections,Blocks}{In,From}Folder`; new
  `children(parent:)`. `Block.dataset` and `File.dataset` → `folder`.
- **Files**: `fromFileLike(input: {file, fileName, folder, exportOf})` — `name` became
  `fileName`, `origins` and `dataset` are gone; `createFileLink` / `deleteFileLink` →
  `linkFile` / `unlinkFile`; `File.links` → `derivedContainers` / `exportedFrom`;
  `File.origins`, `pinFile` and `deleteEra` are removed.
- **Interpretation by id.** `createBlock` signals take `dataset` (and `timesDataset`,
  `waveformsDataset`) — no `trace`, `axes`, `unit`, `timesUnit`, `waveformAxes`,
  `waveformUnit` or `channels`; `createSimulation` recordings and stimuli take `dataset`,
  and `timeTrace` is `timeDataset`. The `valueUnit` arrives through `anchors`.
  `AnalogSignalChannel`, its query and its delete are removed (→ `ChannelLabel` anchors);
  `BlockGroup.channels` with it. `deleteBlock` and `deleteSimulation` no longer delete data.
- **Read-backs:** `IrregularlySampledSignal.timeTrace` / `Simulation.timeTrace` →
  `timeDataset`; new `Recording.samplingRate` / `.tStart`, `Stimulus.samplingRate` /
  `.tStart`; `Simulation.samplingRate` is the *common* rate of its datasets, or null.
- **Removed earlier in this branch:** the `ROI` type, `RoiKind`, `createRoi` / `updateRoi` /
  `pinRoi` / `deleteRoi`, the `rois` query and subscription — replaced by `Annotation`,
  `AnnotationCollection` and their mutations; `Trace.kind`, `Trace.events`;
  `AnalogSignal.unit`, `.timeTrace`; `Experiment.timeTrace` and
  `CreateExperimentInput.timeTrace`; `BlockSegment.endTime`; the `View`, `TimelineView`,
  `ViewCollection`, `FileView` and `Instrument` types and their mutations; the enums
  `TraceKind`, `ViewKind`, `ColorFormat`, `ColorMap`, `Blending`; the scalars `Micrometers`,
  `Milliseconds`, `Microliters`, `Micrograms`.
- **Changed:** an analog signal is **one `(t, c)` dataset**, not an array per channel — the
  Python client must stop rejecting arrays of rank > 1 and stop naming the single dimension
  `"c"`. `createSimulation` takes exactly one of `sampling` and `timeDataset`. A view's
  `offset` is per simulation, and `duration` on input became `window`. `Recording.position`
  / `Stimulus.position` are floats in the database as well as the API.
- **Unchanged in name, now derived:** `AnalogSignal.samplingRate` / `.tStart`,
  `Block.recordingTime`, `BlockSegment.startTime`, `…View.offset` / `.duration`.

## Not done

- **Spatial residents.** `SPACE` axes and spatial systems can be authored and registered
  into, but nothing lives in one: no probe, electrode or morphology model. A site's `cell` /
  `location` / `position` stay descriptive, and a units table's depth is an attribute column,
  not a coordinate -- a probe space would make it one. A collection is one line in
  `graph.CONTAINERS` with `is_collection=True`; the dormant collection machinery is untouched.
- **Waveforms.** Per-unit templates are an array dataset `(unit, c, w)` derived from the raster
  (UNMAPPABLE); its `w` axis is not lowered to a peri-spike clock, and per-*spike* waveforms
  are not modelled -- a raster enumerates no spikes an array axis could be keyed by.
- **Sparse colourings.** mikro colours a label layer by one slice of a matrix (`kind: SPARSE`);
  here pickers are COLUMN-only, so a unit cannot yet be coloured by, say, its firing rate in a
  window. `pickers.assert_sparse_dataset_not_in_a_picker` already guards the JSON for it.
- **Server-side windows over spikes and events.** A spikes or events layer shows its whole
  dataset; the viewer windows it. A raster's CSC layout makes a window one contiguous read
  for a client that asks.
- **Unit-converting lookups.** A times dataset must be in the clock's unit. `SEQUENCE[FIELD, SCALE]`
  would lift that.
- **Non-contiguous selections.** A lens slices `start:stop:step`; channels `[0, 3, 7]` are
  three lenses. (`BlockGroup.channels` went with `AnalogSignalChannel`.)
- **Attaching an anchor after ingest.** Anchors are written by `createArrayDataset` only;
  mikro has the same gap outside its phasor spokes. A series resistance measured afterwards
  has no mutation yet.
- **mikro's scene-only fields** have no counterpart: `defaultScene`, `latestSnapshot`,
  `Lens.renderAxes`, snapshots, animations. What draws a dataset is asked the other way:
  `ArrayDataset.experimentLayers`, `.simulations`.
- **Annotation subscriptions.** mikro has none and neither does this; the `rois`
  subscription went with the ROI.
- **Subscriptions.** `arrayDatasets` is scoped by organization channel and works. `files` reads
  its rows scoped, but nothing broadcasts to it yet.
- **The Python client** (`packages/elektro`) is not updated by this change, nor by the first
  pass: it still speaks `createBlock` and the view inputs.
