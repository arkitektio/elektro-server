"""Typed models for a recorded electrophysiology rig state.

The hardware truth at the moment of acquisition -- clamp mode, holding level, the
compensation the amplifier was set to, per-device settings -- as composable pydantic models
with kanne quantities, mirrored into GraphQL input and output types. ``rigkit`` is to a rig
what mikro's ``optikit`` is to a microscope, and is built the same way on purpose: the state
is stored on :class:`core.models.RigState.state` as the model's dump and reconstructed on
read, so the JSON column never grows a shape the types cannot express.
"""
