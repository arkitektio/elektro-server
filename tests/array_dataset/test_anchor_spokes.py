"""The coordinate-anchor metadata spokes written at ingest.

Ported from mikro's ``tests/test_anchor_spokes.py``, where the spoke is the microscope
(Optikit) state; here it is the rig.

The rig state is the hardware truth -- which quantity was clamped and at what level, what the
amplifier measured of the access and the membrane, per-device settings at the moment of
acquisition -- and it is a spoke like the others: pinned to an anchor, written once at ingest,
never fabricated later. It is *typed*: composable input types with quantities, the model's
dump as the stored JSON, and the same model reconstructed on read.

mikro's version patches ``ZarrStore.fill_info``; this one creates through the
``create_array_dataset`` fixture, over a real ``zarr.json`` in the compose RustFS.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models
from rigkit.models import RigStateModel
from tests import seed

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


TC = [{"name": "t", "type": "TIME"}, {"name": "c", "type": "CHANNEL"}]

ACTIVE_ANCHORS = """
query Read($id: ID!) {
  lens(id: $id) {
    activeAnchors {
      coordinates
      rig {
        state {
          mode
          holdingPotential
          holdingCurrent
          seriesResistance
          membraneCapacitance
          temperature
          devices { label kind settings { name quantity number text flag } }
        }
      }
      acquisitionMetadata { metadata }
      valueUnit { unit dimension }
      channelLabel { label }
    }
  }
}
"""


_STATE_INPUT = {
    "mode": "VOLTAGE_CLAMP",
    "holdingPotential": "-70 mV",
    "seriesResistance": "12.5 Mohm",
    "membraneCapacitance": "33 pF",
    "temperature": "305.15 K",
    "devices": [
        {
            "label": "multiclamp-700b-1",
            "kind": "amplifier",
            "settings": [
                {"name": "lowpass", "quantity": "10 kHz"},
                {"name": "whole-cell compensation", "flag": True},
            ],
        },
        {
            "label": "perfusion-1",
            "settings": [{"name": "solution", "text": "ACSF"}],
        },
    ],
}

_SNAKE = {"holdingPotential": "holding_potential", "seriesResistance": "series_resistance", "membraneCapacitance": "membrane_capacitance"}


def _sent() -> RigStateModel:
    """The state a client sent, as the model the input converts to."""
    return RigStateModel(**{_SNAKE.get(key, key): value for key, value in _STATE_INPUT.items()})


async def test_a_rig_state_is_written_as_a_typed_anchor_spoke(aexecute, create_array_dataset, authenticated_context):
    """Ingest pins the recorded rig state to its coordinate, through composable typed input.

    Quantities arrive as unit-carrying strings and are stored canonically; the stored
    JSON is exactly the model's dump. (That reconstructing it recovers the same *model* is
    mikro's next assertion, and is `test_the_stored_rig_state_reconstructs_the_state_that_was_sent`.)
    """
    created = await create_array_dataset("Acquired", [1000, 2], axes=TC, anchors=[{"axisAnchors": [{"axis": "c", "value": 0}], "rig": _STATE_INPUT}])

    spoke = await models.RigState.objects.aget(anchor__dataset_id=created["id"])
    anchor = await sync_to_async(lambda: spoke.anchor)()
    assert anchor.coordinates == {"c": 0}, "the hardware truth is pinned to the coordinate it was recorded at"

    assert spoke.state == _sent().model_dump(mode="json"), "the typed model's dump IS the stored JSON, so the column never grows a shape the types cannot express"
    stored = RigStateModel(**spoke.state)
    assert (stored.mode, stored.holding_potential, stored.series_resistance, stored.membrane_capacitance, stored.temperature) == (_sent().mode, _sent().holding_potential, _sent().series_resistance, _sent().membrane_capacitance, _sent().temperature), "the dimension-locked quantities compare canonically, not by their spelling"
    assert stored.devices[0].settings[0].name == "lowpass"
    assert stored.devices[1].settings[0].text == "ACSF"

    # And back out through GraphQL: the typed read surface, quantities as scalars.
    dataset = await models.ArrayDataset.objects.aget(pk=created["id"])
    lens = await seed.create_lens(authenticated_context, dataset, slices=[])
    read = await aexecute(ACTIVE_ANCHORS, {"id": str(lens.pk)})
    assert not read.errors, read.errors
    (read_anchor,) = read.data["lens"]["activeAnchors"]
    state = read_anchor["rig"]["state"]
    assert state["mode"] == "VOLTAGE_CLAMP"
    assert state["holdingPotential"] is not None and state["holdingCurrent"] is None
    assert state["devices"][0]["label"] == "multiclamp-700b-1"
    assert state["devices"][0]["settings"][0]["quantity"] is not None
    assert state["devices"][1]["settings"][0]["text"] == "ACSF"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "kanne_server/quantities.py::_generic_markers.validate: a GenericQuantity's in-memory string is not normalized across a storage round trip. "
        "'10 kHz' validates to '10 kilohertz' (pint keeps the int magnitude), its JSON dump is {'magnitude': 10.0, ...} (generic_quantity_struct floats it), "
        "and reading that back formats f'{10.0} kilohertz' == '10.0 kilohertz'. The two strings are the same quantity and compare unequal, so a device setting "
        "with an integer-valued quantity breaks RigStateModel equality after one save. mikro's vendored copy is identical ('20 milliwatt' vs '20.0 milliwatt')."
    ),
)
async def test_the_stored_rig_state_reconstructs_the_state_that_was_sent(create_array_dataset):
    """mikro's assertion, verbatim: reconstructing the stored JSON recovers the state the client sent, quantities compared canonically rather than by their spelling."""
    created = await create_array_dataset("Acquired", [1000, 2], axes=TC, anchors=[{"axisAnchors": [{"axis": "c", "value": 0}], "rig": _STATE_INPUT}])
    spoke = await models.RigState.objects.aget(anchor__dataset_id=created["id"])

    stored = RigStateModel(**spoke.state)
    assert stored == _sent()


async def test_a_setting_holds_exactly_one_value(create_array_dataset):
    """A setting filling two value slots is refused: it is two settings."""
    rig = {"devices": [{"label": "amplifier", "settings": [{"name": "lowpass", "quantity": "10 kHz", "number": 10000.0}]}]}
    result = await create_array_dataset("Broken", [1000, 2], axes=TC, anchors=[{"axisAnchors": [], "rig": rig}], raw=True)
    assert result.errors
    assert "one value" in str(result.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="Broken").aexists(), "one transaction here, which mikro's is not: the refusal leaves no dataset behind"
    assert await models.CoordinateSystem.objects.acount() == 0


@pytest.mark.parametrize(
    ("rig", "fragment"),
    [
        ({"mode": "VOLTAGE_CLAMP", "holdingCurrent": "50 pA"}, "contradicts `mode: VOLTAGE_CLAMP`"),
        ({"mode": "CURRENT_CLAMP", "holdingPotential": "-70 mV"}, "contradicts `mode: CURRENT_CLAMP`"),
        ({"mode": "ZERO_CURRENT", "holdingCurrent": "0 pA"}, "holds nothing"),
    ],
    ids=["voltage-clamp", "current-clamp", "zero-current"],
)
async def test_a_holding_level_may_not_contradict_the_clamp_mode(create_array_dataset, rig: dict, fragment: str):
    """The holding level is the level of whatever was *clamped*: stating the other one is a contradiction, not extra information."""
    result = await create_array_dataset("Contradiction", [1000, 2], axes=TC, anchors=[{"axisAnchors": [], "rig": rig}], raw=True)
    assert result.errors and fragment in str(result.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="Contradiction").aexists()


async def test_a_lens_reads_the_spokes_of_the_channels_it_keeps(aexecute, create_array_dataset, authenticated_context):
    """Every spoke kind this service has, on one dataset, read back through a lens that keeps one channel.

    The dataset-wide anchor is global along every axis, so it is always in; a channel's anchor
    is in only while the slice keeps that channel.
    """
    anchors = [
        {"axisAnchors": [], "valueUnit": {"unit": "mV"}, "acquisitionMetadata": {"metadataString": '{"protocol": "IV"}'}},
        {"axisAnchors": [{"axis": "c", "value": 0}], "label": {"label": "Vm"}},
        {"axisAnchors": [{"axis": "c", "value": 1}], "label": {"label": "Icmd"}, "valueUnit": {"unit": "pA"}},
    ]
    created = await create_array_dataset("Paired", [1000, 2], axes=TC, anchors=anchors)
    dataset = await models.ArrayDataset.objects.aget(pk=created["id"])

    command_only = await seed.create_lens(authenticated_context, dataset, slices=[{"axis": "c", "start": 1, "stop": 2}])
    read = await aexecute(ACTIVE_ANCHORS, {"id": str(command_only.pk)})
    assert not read.errors, read.errors
    by_coordinates = {str(anchor["coordinates"]): anchor for anchor in read.data["lens"]["activeAnchors"]}

    assert set(by_coordinates) == {"{}", "{'c': 1}"}, "channel 0's label is outside the slice"
    assert by_coordinates["{}"]["valueUnit"]["unit"] == "mV"
    assert by_coordinates["{}"]["acquisitionMetadata"]["metadata"] == {"protocol": "IV"}
    assert by_coordinates["{'c': 1}"]["channelLabel"]["label"] == "Icmd"
    assert by_coordinates["{'c': 1}"]["valueUnit"] == {"unit": "pA", "dimension": "[current]"}
    assert all(anchor["rig"] is None for anchor in by_coordinates.values()), "an unstated spoke is null, not an empty state"


async def test_acquisition_metadata_must_be_a_json_object(create_array_dataset):
    for bad, fragment in (("not json", "is not valid JSON"), ("[1, 2]", "must be a JSON object")):
        result = await create_array_dataset("Meta", [10], anchors=[{"axisAnchors": [], "acquisitionMetadata": {"metadataString": bad}}], raw=True)
        assert result.errors and fragment in str(result.errors[0]), bad
    assert not await models.ArrayDataset.objects.filter(name="Meta").aexists()


# --- elektro's addition: an anchor is checked against the axes it pins --------------------------


async def test_an_anchor_may_not_name_an_axis_twice(create_array_dataset):
    """One position per axis; a second position is a second anchor."""
    twice = {"axisAnchors": [{"axis": "c", "value": 0}, {"axis": "c", "value": 1}], "label": {"label": "both"}}
    result = await create_array_dataset("Twice", [1000, 2], axes=TC, anchors=[twice], raw=True)
    assert result.errors and "An anchor names an axis once" in str(result.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="Twice").aexists()


async def test_an_anchor_may_not_name_an_axis_the_dataset_lacks(create_array_dataset):
    result = await create_array_dataset("Unknown", [1000, 2], axes=TC, anchors=[{"axisAnchors": [{"axis": "sweep", "value": 3}], "label": {"label": "s3"}}], raw=True)
    assert result.errors and "['sweep'] is not among ['t', 'c']" in str(result.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="Unknown").aexists()


async def test_two_anchors_may_not_share_their_coordinates(create_array_dataset):
    """A spoke is one-to-one with its anchor, so a second anchor at the same place is a rival answer to the first."""
    rivals = [{"axisAnchors": [], "valueUnit": {"unit": "mV"}}, {"axisAnchors": [], "acquisitionMetadata": {"metadataString": "{}"}}]
    result = await create_array_dataset("Rivals", [1000, 2], axes=TC, anchors=rivals, raw=True)
    assert result.errors and "Two anchors are pinned to the same coordinates {} (the whole dataset)" in str(result.errors[0])
    assert not await models.ArrayDataset.objects.filter(name="Rivals").aexists()

    # The same two spokes on the one anchor are what the refusal asks for.
    merged = [{"axisAnchors": [], "valueUnit": {"unit": "mV"}, "acquisitionMetadata": {"metadataString": "{}"}}]
    accepted = await create_array_dataset("Rivals", [1000, 2], axes=TC, anchors=merged, raw=True)
    assert not accepted.errors, accepted.errors
