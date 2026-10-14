# elektro

Notes for whoever changes this service, person or agent.

## Migrations and jobs

A container of this image only serves. An installer (konstruktor) prepares the database with
`arkitekt-service run migrate` once per build — before the first start, and in an update before
anything is recreated — and runs everything else as a job the image offers by name
(`konstruktor job run elektro <job>`). Nothing is migrated, seeded or repaired at start.

**Read the rules before changing a model, a management command or `elektro_server/contract.py`:**
<https://github.com/arkitektio/arkitekt-service/blob/main/docs/migrations-and-jobs.md>. The ones that are broken most easily:

- A model change and its migration are one commit.
- Within a major, a migration leaves a schema the previous release still runs on: a failed
  update, and a rollback, start the old build on the migrated database. What cannot do that
  is a `feat!:`.
- A `manage.py` command an operator should be able to run on a hub is declared in `jobs=` in
  `elektro_server/contract.py`; one nobody runs is deleted. Any job is safe to run again.
- What `setup=` names runs for every build, after the migrations: it changes nothing the
  second time and needs nothing but the database and the config.
- Existing data is rewritten by a data migration when that needs only the database (it runs
  once, with the service stopped), and by a re-runnable job in `setup=` when it needs the
  service's code or its storage. There is no upgrade step, and nothing is keyed to a version.

What this service declares:

- Setup, in order: `ensureadmin`, `restore_descriptors`. The second stores the descriptors of
  every row that misses a declared key (rows from before the key existed); `--all` describes
  every row again after a describer changed what a key means.
- Other jobs: `purge_orphaned_stores`, `respec_datasets`.

`tests/test_prepared.py` holds the contract to this: migrations committed, every job a command
of this service, the setup run twice. In `deployments/next` the service runs
`arkitekt-service standalone --debug`, which migrates and then serves: restart its container
to apply a new migration.

## Descriptors

Every descriptor is stored (`stored_descriptors` on `ArrayDataset` and `Lens`, recomputed on every
save by `arkitekt_service`), so a port's `requires` is the `requires` argument of the dataset and
lens filters: one indexed query (`core.logic.descriptor_filter`, mikro's by path). Nothing is only
stated: `@elektro/value_dimension` is read off the dataset-wide `ValueUnit` in the client's words
(`elektro.specs.value_dimension`), `@elektro/value_kind` off the primary derivation (categorical
or continuous). What a save cannot see is restored by its writer (`core.descriptors.restore`):
`createArrayDataset` restores its dataset at its end, and every save or delete of a `ValueUnit` or
a `Transformation` restores the datasets it concerns and their lenses (`core/signals.py`). A test
that seeds a dataset by hand restores it too (`tests/seed.py`).
