"""What a test receives when it names one of the suite's fixtures (``tests/conftest.py``).

The factories are Protocols: a test annotates its argument with the factory's type, and the
fixture's own function is checked against the same signature.
"""

from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeAlias, overload

from arkitekt_datalayer.models import BigFileStore, ZarrStore
from kante.context import HttpContext
from numpy.typing import NDArray
from strawberry.types import ExecutionResult

from core.models import (
    ArrayDataset,
    CoordinateSystem,
    Folder,
    ModEnvironment,
    NeuronModel,
)

#: A GraphQL payload, as strawberry hands it over: ``ExecutionResult.data`` is ``dict[str, Any]``.
GraphQLData: TypeAlias = dict[str, Any]

#: The host ports the compose stack published: ``{"db": ..., "rustfs": ...}``.
BackendStack: TypeAlias = dict[str, int]


class AExecute(Protocol):
    """``aexecute``: run a GraphQL document as one request, as the authed identity by default."""

    def __call__(
        self,
        query: str,
        variables: Mapping[str, object] | None = None,
        context: HttpContext | None = None,
    ) -> Awaitable[ExecutionResult]: ...


class ZarrStoreFactory(Protocol):
    """``zarr_store``: a ZarrStore row, its zarr.json seeded in RustFS unless ``seed=False``."""

    def __call__(
        self,
        context: HttpContext | None = None,
        seed: bool = True,
        shape: Sequence[int] | None = None,
        dimension_names: Sequence[str | None] | None = None,
    ) -> Awaitable[ZarrStore]: ...


class CreateArrayDatasetFactory(Protocol):
    """``create_array_dataset``: the ``createArrayDataset`` payload, or the raw result with ``raw=True``."""

    @overload
    def __call__(
        self,
        name: str = "dataset",
        shape: Sequence[int] | None = None,
        *,
        axes: Sequence[Mapping[str, object]] | None = None,
        value_unit: str | None = None,
        anchors: Sequence[Mapping[str, object]] | None = None,
        levels: Sequence[tuple[Sequence[int], str | None]] | None = None,
        derived_from: object = None,
        folder: int | str | None = None,
        context: HttpContext | None = None,
        raw: Literal[False] = False,
    ) -> Awaitable[GraphQLData]: ...

    @overload
    def __call__(
        self,
        name: str = "dataset",
        shape: Sequence[int] | None = None,
        *,
        axes: Sequence[Mapping[str, object]] | None = None,
        value_unit: str | None = None,
        anchors: Sequence[Mapping[str, object]] | None = None,
        levels: Sequence[tuple[Sequence[int], str | None]] | None = None,
        derived_from: object = None,
        folder: int | str | None = None,
        context: HttpContext | None = None,
        raw: Literal[True],
    ) -> Awaitable[ExecutionResult]: ...


class BigFileStoreFactory(Protocol):
    """``bigfile_store``: a BigFileStore row, its bytes put in RustFS unless ``content=None``."""

    def __call__(
        self,
        context: HttpContext | None = None,
        content: bytes | None = b"elektro",
        **kwargs: object,
    ) -> Awaitable[BigFileStore]: ...


class DatasetFactory(Protocol):
    """``make_dataset``: an ArrayDataset row with no grid and no levels."""

    def __call__(
        self,
        context: HttpContext | None = None,
        name: str = "dataset",
        folder: Folder | None = None,
    ) -> Awaitable[ArrayDataset]: ...


class NeuronModelFactory(Protocol):
    """``make_neuron_model``: a NeuronModel row with the space it owns."""

    def __call__(
        self,
        context: HttpContext | None = None,
        name: str = "NeuronModel",
        environment: ModEnvironment | None = None,
        json_model: Mapping[str, object] | None = None,
    ) -> Awaitable[NeuronModel]: ...


@dataclass(frozen=True)
class SimulationChain:
    """A run of a NeuronModel, as ``make_simulation_chain`` builds it."""

    neuron_model: NeuronModel
    clock: CoordinateSystem
    grid: CoordinateSystem
    stimulus_grid: CoordinateSystem
    recording: ArrayDataset
    stimulus: ArrayDataset
    time_dataset: ArrayDataset | None


class SimulationChainFactory(Protocol):
    """``make_simulation_chain``: a clock, and a recorded and an injected output timed onto it."""

    def __call__(
        self,
        context: HttpContext | None = None,
        *,
        name: str = "sim",
        samples: int = 400,
        rate: str = "10 kHz",
        t_start: str = "0 ms",
        timing: str = "sampling",
        unit: str = "millisecond",
    ) -> Awaitable[SimulationChain]: ...


#: A grant as ``requestZarrUpload`` / ``requestZarrAccess`` answer it (GraphQL data).
Grant: TypeAlias = Mapping[str, Any]


class ZarrUploader(Protocol):
    """``upload_zarr_to_grant``: write a real Zarr v3 array through a grant's credentials."""

    def __call__(
        self,
        grant: Grant,
        shape: tuple[int, ...] = (4, 4),
        chunks: tuple[int, ...] = (4, 4),
    ) -> Awaitable[None]: ...


class ZarrReader(Protocol):
    """``read_zarr_from_grant``: read a Zarr array back through a grant's credentials."""

    def __call__(self, grant: Grant) -> Awaitable[NDArray[Any]]: ...
