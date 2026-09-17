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
  under the same identifiers: `ArrayDataset`, `DataArray`, `Lens`, `CoordinateSystem`,
  `Transformation`, `CoordinateAnchor` and its spokes, `AnnotationCollection`, `Folder`,
  `File`, `FileLink`, and the mutations that write them (`createArrayDataset`, `createLens`,
  `createCoordinateSystem`, `linkFile`, …). `diff` the two copies of any of these files and
  what is left is a short, commented list. This layer knows nothing about electrophysiology.
- **The interpretation layer is elektro's.** mikro reads an array as a *layer of a scene*;
  elektro reads it as a *signal of a block*, a *recording of a simulation*, a *view of an
  experiment*. Like a scene, an interpretation **names data by id and owns none of it**: it
  never creates an array, and deleting it never deletes one.

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
| a **sample grid** — a dataset's axes, typed, never carrying a unit (mikro: the pixel grid) | a **sampling law** — `t = sample · period + t_start`, one affine edge (mikro: pixel size + stage position) | an **`ArrayDataset`** — a recording, a stimulus, a vector of sample times, a spike train |
| a **level's grid** — a decimated copy's own sample indices | a **level edge** — scale and half-sample shift back into the recording's grid | a **`DataArray`** — one pyramid level; level 0 *is* the dataset's grid |
| a **clock** — one `TIME` axis in a time unit, optionally anchored to a wall-clock `epoch` | a **time lookup** — a `FIELD` whose map is the values of a times dataset | a **`Lens`** — an immutable selection over a dataset |
| a **world** — the clock an experiment is laid out on | an **offset** — where one clock sits on another | an **`AnnotationCollection`** — a set of marks, owning the space they are drawn in |
| a **drawing space** — an annotation collection's own | a **derivation** — how a computed dataset's grid maps back into its source's | |

Four rules carry over from mikro unchanged:

1. **Edges are facts, paths are queries.** No composed map is stored anywhere. The same
   recording can sit in two experiments under two offsets, so any single stored answer
   would be wrong in one of them. Composing on read is fine (`asAffine`); storing the result
   is what is forbidden. Refine one edge and everything that looks through it moves.
2. **Store what was authored or measured; derive everything else.** A sampling rate was
   measured, so it is stored — once, on the edge. `AnalogSignal.samplingRate` is a *reading*
   of that edge. A lens' shape follows from its dataset and its slices, so it is not a column.
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

**Filing** is mikro's too: `Dataset` became **`Folder`** (the old name collided with the data
it filed), its foreign keys are `SET_NULL` — deleting a folder *unfiles*, where the old
`Dataset` cascaded into every file in it — and derived data follows its primary parent
(`core/logic/folder.py`). A `Block` is fileable as well. A **`FileLink`** relates a file's
bytes to a container, from either end (`sourceFiles`, `exportOf`, `linkFile`), and is
deliberately not a derivation: a file has no space.

**Stores outlive their data.** No delete mutation touches S3. A delete flags the stores it
leaves unreferenced (`orphaned_at`), and `manage.py purge_orphaned_stores` collects them
after `DATALAYER_STORE_GRACE_DAYS`, re-checking for referrers first (`core/logic/storage.py`).

## The interpretation layer

| mikro | elektro |
|---|---|
| `Scene` over a `world` | `Experiment` over a `world`; also `Block` / `BlockSegment` / `Simulation`, each laid out on a `clock` |
| `Layer` naming a `Lens` | `ExperimentRecordingView` / `ExperimentStimulusView` naming a `Lens`; `AnalogSignal` / `IrregularlySampledSignal` / `SpikeTrain` / `Recording` / `Stimulus` naming an `ArrayDataset` |
| `createScene`, `createLayer` | `createBlock`, `createSimulation`, `createExperiment` |

An interpretation mutation takes **ids of datasets that already exist** and writes only
what it means for them to be a session or a run: a clock, a row per dataset, and **one
timing edge per dataset** onto that clock (`core/logic/clocks.py` is the one writer). There
is no `axes`, `unit` or `channels` on a signal — those are facts of the dataset and were
said when it was created. What an interpretation checks is that the dataset can *bear* it:

| | Input | Refused unless |
|---|---|---|
| analog signal | `dataset`, `samplingRate`, `tStart`, `validity` | the dataset has a `TIME` axis for the law to act on |
| irregular signal | `dataset`, `timesDataset` | one instant per sample; the times dataset lives alone in its system (R3) and its `ValueUnit` is the clock's unit |
| spike train | `dataset`, `waveformsDataset`, `tStart`, `tStop` | the dataset has exactly one axis and it is `INDEX` (its name is read, not assumed) |
| simulation | `recordings` / `stimuli` `{dataset, kind, site…}`, `timeDataset` **xor** `sampling` | every dataset has a `TIME` axis and the same sample count |

And in every case: **one dataset is timed once on one clock**. Two edges between the same
two spaces are rivals the path search chooses between, so naming a dataset twice against
one clock is refused (`clocks.TimedOnce`).

Deleting an interpretation deletes the interpretation: `deleteBlock` and `deleteSimulation`
remove their rows and sweep the clocks left empty — which takes the timing edges onto those
clocks, and the offsets out of them, along — and leave every dataset where it was.
Deleting a single signal, recording or stimulus removes its own timing edge with it.
The other direction does cascade: `deleteArrayDataset` takes the signals and recordings
that named it, because an interpretation of data that no longer exists is one of nothing.

## What was mapped onto what

| Was a column | Is now |
|---|---|
| `AnalogSignal.sampling_rate`, `.t_start` | the **sampling law**: one `BY_DIMENSION` edge carrying a 1×2 affine, sample grid → segment clock |
| `AnalogSignal.time_trace` | gone — it was a second copy of the same fact, free to disagree with the first |
| `IrregularlySampledSignal.time_trace` | the field of a **time lookup**: a `FIELD` edge, signal grid → segment clock |
| *(spike times had no relation to time at all)* | a self-field `FIELD` edge, spike grid → segment clock |
| `Block.recording_time` | the `epoch` of the block's `clock` |
| `BlockSegment.start_time` / `.end_time` | an offset edge, segment clock → session clock; `endTime` is gone |
| `Simulation.time_trace` | the field of the run's time lookups (`timeDataset`) — or absent, when the run has sampling laws |
| `Experiment.time_trace` | `Experiment.world`, a space it adopts and never owns |
| `ExperimentRecordingView.offset`, `ExperimentStimulusView.offset` | **one** offset edge per simulation clock → world |
| `…View.duration` | the slices of the view's `Lens` |
| `AnalogSignal.unit`, `AnalogSignalChannel.unit`, `SpikeTrain.unit` | a `ValueUnit` anchor on the dataset (`{}`, or `{c: i}` per channel) |
| `AnalogSignalChannel` (`index`, `name`) | a `ChannelLabel` anchor at `{c: index}` |
| `Trace` (one store) | `ArrayDataset` + a `DataArray` per level |
| `Trace.kind` | derived: the dimensionality of the value unit (`valueDimension`) |
| `Trace.tags`, `.pinned_by` | gone, as in mikro: file it in a `Folder` |
| `Dataset` | `Folder` |
| abstract `View` (`a_min…c_max`), `TimelineView`, `ViewCollection` | `Lens` |
| `FileView` | `FileLink` — a link to a file is not a selection over a dataset |
| `ROI` (`trace` FK, `min_t` / `max_t` in samples, kinds `LINE` `POINT` `SPIKE` `SLICE`) | `Annotation` in an `AnnotationCollection` — see below |

Everything in the right-hand column that a client used to read is still readable, under the
same name where there was one (`samplingRate`, `tStart`, `recordingTime`, `startTime`,
`offset`, `duration`; `timeTrace` is `timeDataset`) — derived on read, from the edge.

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
law could not be stated. `INDEX` is for what genuinely has none: a sweep, a trial, a spike
number — which is exactly why a spike train reaches time through a lookup and not a rate.

### Annotations

An `ROI` hung off one trace by a foreign key and kept its extent in two integer columns of
sample indices, so it could mark one array and nothing else, in one unit and no other. It
is replaced by mikro's annotation model (`core/models/annotation.py`, vendored): an
`Annotation` belongs to an `AnnotationCollection`, the collection **owns the coordinate
system its shapes are drawn in**, and what that space is related to — by an edge, never by
a second FK on the shape — decides what the marks mean:

- drawn over a **dataset's sample grid**, a collection marks that dataset, in samples;
- drawn on a **segment's clock**, it marks *every signal of the segment at once*, in the
  clock's unit. This is what Neo's events and epochs are: they belong to the segment;
- drawn on an **experiment's world**, it marks the timeline and everything laid out on it.
  `createAnnotation(experiment:)` is the sugar for this: the first mark mints the
  experiment's collection — a space copying the world's axes, an identity edge into the
  world, and one `ExperimentAnnotationView` — and later marks append to it. Deleting the
  experiment keeps what was drawn; only the view cascades.

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
Three things stay columns although they are about time:

- `Simulation.dt` and `.duration` are the **integrator's** parameters (NEURON's `h.dt`,
  `h.tstop`). A run can record at a coarser interval than it integrates, so `dt` is not the
  sampling period and must not be read as one. `dt` is nullable: its old default was one
  *second*.
- `SpikeTrain.t_start` and `.t_stop` are the **observation window**, which the spike times
  cannot reproduce: no spikes over ten seconds is a different measurement from no spikes
  over a hundred.

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

Signals, recordings and stimuli are **not** residents. They name a dataset; making them
containers would give one array two homes.

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
2. **Views over lookup-timed data are admitted.** mikro's [rfc10](../docs/rfc10-affine-placement-gate.md)
   refuses a layer whose route does not condense into one affine map. A spike train, an
   irregular signal and a variable-step simulation all reach time across a `FIELD`, which
   never condenses, and a timeline can draw them without a matrix. `createExperiment` gates
   on *reachability*; such a view reports `placement: PLACED`,
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
   Four things are laid out over a space here — an experiment, a block, a segment, a
   simulation — so it is a registry, read by the delete guard, the orphan sweep and
   `sweep_empty_systems`. `tests/test_architecture.py` derives it from the foreign keys, so
   a fifth composition is a failing test rather than a clock swept out from under it.
7. **A space leaves with what it was for.** Nothing owns a space, and a dataset's FK to its
   grid is `PROTECT`, so neither can cascade. `deleteArrayDataset`, `deleteDataArray` and
   `deleteLens` delete the data and then sweep the grids left empty; `deleteBlock` and
   `deleteSimulation` sweep the *clocks* left empty (`spaces.sweep_empty_systems`). mikro
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

12. **The data layer's three additions**, listed under "The data layer" above: an atomic
    `createArrayDataset`, anchors checked against the axes, and a `ValueUnit` spoke. And one
    substitution: `rigkit` for `optikit`, `AcquisitionMetadata` for `OmeMetadata`.
13. **One delete predicate.** mikro passes an `owner` callable per model; this service has
    `core/guards.py` (`ANCHOR_PATHS`), so `core/mutations/_generic.py::make_delete` takes no
    `owner`. The store straddle — collect, delete, flag — is mikro's.

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

```graphql
mutation {
  createBlock(input: {
    name: "session 12", recordingTime: "2026-09-17T09:00:00Z",
    segments: [{ name: "baseline", startTime: "0 s", analogSignals: [{
      dataset: "41", samplingRate: "30 kHz", tStart: "2 s" }] }]
  }) {
    clock { epoch }
    segments { analogSignals {
      samplingRate tStart                       # derived from ↓
      samplingLaw { kind validity ... on ByDimensionTransformation { transformations { ... on AffineTransformation { affine } } } }
      dataset { valueUnit intrinsicSystem { axes { name type unit } } }
    } }
  }
}
```

```graphql
mutation {
  createExperiment(input: { name: "paired pulse",
    recordingViews: [{ recording: "7", offset: "50 ms", window: { start: "0 ms", stop: "200 ms" } }],
    stimulusViews:  [{ stimulus:  "9", offset: "50 ms" }] }) {
    world { registrations { kind } }            # ONE edge, shared by both views
    recordingViews { placement placementValidity asAffine { matrix } pathToWorld { transformation { kind } } lens { activeAnchors { channelLabel { label } } } }
  }
}
```

`offset` and `window` are *input sugar*, lowered once: `offset` to one edge per clock (two
views of one simulation stating different offsets are refused, by name), `window` to a lens
in sample indices by inverting the sampling law (refused over a lookup, which has no
closed-form inverse — cut a lens in samples with `createLens` instead).

## Migrations

The initial migration was **regenerated** (as mikro did). A data migration would have had to
re-implement edge derivation against historical models — a second copy of the logic this
design forbids — and could never be tested, because the test settings disable migrations.
It creates the Postgres `cube` extension first (hand-added, as in mikro: `makemigrations`
cannot emit it), so the database role needs the right to `CREATE EXTENSION`.
Deploying this requires resetting the elektro database; stores whose rows are dropped become
orphaned objects in S3. The datalayer app gained one ordinary migration
(`0002_datalayerstore_orphaned_at`). `tests/test_architecture.py` checks that the models and the
migration agree, and that the migration actually runs on an empty Postgres.

## Breaking changes for API clients

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
  into, but nothing lives in one: no probe, electrode or morphology model.
  `Recording.cell` / `.location` / `.position` stay descriptive. A collection is one line in
  `graph.CONTAINERS` with `is_collection=True`; the dormant collection machinery is untouched.
- **Waveform timing.** A spike train's `waveforms` dataset is named, but `leftSweep` and the
  waveform sampling rate are not yet lowered to an edge into a peri-spike clock.
- **Unit-converting lookups.** A times dataset must be in the clock's unit. `SEQUENCE[FIELD, SCALE]`
  would lift that.
- **Non-contiguous selections.** A lens slices `start:stop:step`; channels `[0, 3, 7]` are
  three lenses. (`BlockGroup.channels` went with `AnalogSignalChannel`.)
- **Attaching an anchor after ingest.** Anchors are written by `createArrayDataset` only;
  mikro has the same gap outside its phasor spokes. A series resistance measured afterwards
  has no mutation yet.
- **mikro's scene-only fields** have no counterpart: `ArrayDataset.scenes`, `defaultScene`,
  `latestSnapshot`, `Lens.renderAxes`. What interprets a dataset is asked the other way:
  `ArrayDataset.analogSignals`, `.recordings`, `.stimuli`, ….
- **Annotation subscriptions.** mikro has none and neither does this; the `rois`
  subscription went with the ROI.
- **Subscriptions.** `arrayDatasets` is scoped by organization channel and works. `files` reads
  its rows scoped, but nothing broadcasts to it yet.
- **The Python client** (`packages/elektro`) is not updated by this change.
