# elektro

Notes for whoever changes this service, person or agent.

## Migrations, jobs and upgrades

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
- Existing data rewritten once is an upgrade into the next major (`upgrades={N: function}` in
  the contract), not a setup job and not a slow `RunPython`.

What this service declares:

- Setup, in order: `ensureadmin`.
- Other jobs: `purge_orphaned_stores`.
- Upgrades: none declared, so the image offers no `upgrade` job.

`tests/test_prepared.py` holds the contract to this: migrations committed, every job a command
of this service, the setup run twice. In `deployments/next` the service runs
`arkitekt-service standalone --debug`, which migrates and then serves: restart its container
to apply a new migration.
