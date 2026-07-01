"""Migrate stored NeuronModel.json_model blobs to the NEURON-compliant schema.

Breaking schema changes (see plan): sections now carry a single ``parent``
connection instead of a ``connections`` list, connections use
``parent_location``/``child_end`` instead of ``location``, sections gain
``ra``/``cm``, and section params carry a ``distribution`` instead of a flat
``value``. This rewrites existing rows so ``ModelConfigModel(**json_model)``
keeps resolving.

The existing ``hash`` is left untouched: it is already unique and stable, and
recomputing it cannot reproduce the exact strawberry-input normalisation a fresh
``createNeuronModel`` uses across a breaking schema change, so recomputation
would add collision risk without restoring dedup parity.
"""

import uuid

from django.db import migrations

# NEURON defaults, in kanne canonical sub-units (bare ints; the quantity
# validators accept a bare canonical int and re-expand on serialization).
RA_DEFAULT = 35_400_000_000      # 35.4 Ω·cm
CM_DEFAULT = 1_000_000_000       # 1 µF/cm²


def _migrate_section(section: dict) -> None:
    # connections[] -> parent (single). Idempotent: skip if already migrated.
    if "connections" in section:
        connections = section.pop("connections") or []
        if connections:
            first = connections[0]
            section["parent"] = {
                "parent": first.get("parent"),
                "parent_location": first.get("location", first.get("parent_location", 1.0)),
                "child_end": first.get("child_end", 0.0),
            }
        else:
            section["parent"] = None
    section.setdefault("ra", RA_DEFAULT)
    section.setdefault("cm", CM_DEFAULT)


def _migrate_compartment(compartment: dict) -> None:
    for param in compartment.get("section_params") or []:
        if "distribution" not in param and "value" in param:
            param["distribution"] = {"kind": "uniform", "value": param.pop("value")}


def _migrate_config(config: dict) -> dict:
    for cell in config.get("cells") or []:
        topology = cell.get("topology") or {}
        for section in topology.get("sections") or []:
            _migrate_section(section)
        biophysics = cell.get("biophysics") or {}
        for compartment in biophysics.get("compartments") or []:
            _migrate_compartment(compartment)
    # net_synapses now require an id to resolve under the type model.
    for synapse in config.get("net_synapses") or []:
        synapse.setdefault("id", str(uuid.uuid4()))
    return config


def forwards(apps, schema_editor):
    NeuronModel = apps.get_model("core", "NeuronModel")
    for model in NeuronModel.objects.all().iterator():
        config = model.json_model or {}
        if not config:
            continue
        model.json_model = _migrate_config(config)
        model.save(update_fields=["json_model"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_fileview_historicalfile_historicalfileview_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
