"""Typed, fully-documented configuration schema for the **elektro** service.

Owned by this service. Values resolve (highest precedence first) from init
kwargs, environment variables (nested via ``__`` — e.g. ``POSTGRES__PASSWORD``),
then the YAML file (``config.yaml`` where the service runs by default; override with
``ARKITEKT_CONFIG_FILE``). Secret fields have **no default**: loading fails fast
with a ``ValidationError`` if they are not supplied via config or environment.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from arkitekt_service.server import settings as shared
from arkitekt_service.server.settings import DjangoSettings, InstanceSettings, PostgresSettings, ServiceSettings
from arkitekt_datalayer.configuration import DatalayerBucket, DatalayerSettings
from authentikate.base_models import AuthentikateSettings

class RedisSettings(shared.RedisSettings):
    """Redis connection (channel layer / cache)."""

    channel_prefix: str = Field(default="elektro", description="Key prefix for the channels_redis channel layer. Must be unique per service: every service on a shared redis used to send under the same prefix, so identically-named groups (e.g. \"files\") delivered one service's events to another's subscribers.")


class ElektroDatalayerSettings(DatalayerSettings):
    """The datalayer block, with the two buckets elektro cannot run without."""

    session_name: str = Field(default="elektro", description="Prefix of every STS session elektro assumes, so an object store's audit log names it.")
    media: DatalayerBucket = Field(description="Bucket for media / general file storage. Required for this service.")
    zarr: DatalayerBucket = Field(description="Bucket for Zarr arrays and sparse matrices. Required for this service.")


class EmbeddingsSettings(BaseModel):
    """Semantic search: a model2vec static model embeds name + description into pgvector columns.

    Every value has a default, so the block may be omitted. The vector width is fixed by the
    model *and* by the database columns; see CONFIG.md before changing ``model``.
    """

    model_config = ConfigDict(extra="allow", protected_namespaces=())

    enabled: bool = Field(default=True, description="Embed rows on save and give `search` a semantic leg. Off: `search` is lexical-only and the embedding columns stay NULL.")
    model: str = Field(default="minishlab/potion-base-8M", description="model2vec model id. Recorded on every row; rows embedded by another model are re-embedded in-process and skipped by vector search until then.")
    model_path: Optional[str] = Field(default=None, description="Directory holding the weights of `model` (save_pretrained layout). The Docker image bakes them under /opt/models and sets EMBEDDINGS__MODEL_PATH; unset, model2vec downloads from Hugging Face on first use.")
    dimensions: int = Field(default=256, description="Vector width of `model`. Also the width of the database columns, so changing it is a migration. Checked against both at startup.")
    distance_threshold: float = Field(default=0.55, description="Cosine distance (0 identical, 1 unrelated) above which a row no longer counts as a semantic `search` hit.")
    sweep_interval: int = Field(default=300, description="No longer used: `reembed_stale` (which re-embeds rows whose `embedding_model` is not `model`) is only offered as an action, and scheduling it is the organization's own automation. Kept so existing configs load.")
    sweep_batch_size: int = Field(default=200, description="Rows re-embedded per pass.")


class RekuestHookSettings(BaseModel):
    """How this process reaches the hub's rekuest: as a service (``rekuest_service``) and as a hook agent (``rekuest_hook``)."""

    rekuest_url: str = Field(default="http://rekuest:80/rekuest", description="rekuest's base URL on the internal network; runs are reported to its `agi/http/<agent>` intake.")
    service: str = Field(default="elektro", description="The name rekuest knows this process by: its `rekuest.services[].name` (signals are sent as it) and its `rekuest.hook_agents[].name`.")
    max_skew: int = Field(default=30, description="Clock skew (seconds) tolerated on a signed request; tokens themselves live 60 s.")


class Settings(ServiceSettings):
    """Top-level, validated configuration for the elektro service."""

    django: DjangoSettings = Field(description="Core Django settings.")
    postgres: PostgresSettings = Field(description="PostgreSQL connection.")
    redis: RedisSettings = Field(description="Redis connection.")
    authentikate: AuthentikateSettings = Field(description="Token-verification config (authentikate).")
    datalayer: ElektroDatalayerSettings = Field(description="S3 storage connection and buckets.")
    embeddings: EmbeddingsSettings = Field(default_factory=EmbeddingsSettings, description="Semantic search model and thresholds.")
    rekuest_hook: Optional[RekuestHookSettings] = Field(default=None, description="Let the hub's rekuest run this service's periodic work (`reembed_stale`). Without it stale embeddings are not healed.")
    instance: Optional[InstanceSettings] = Field(default=None, description="This instance's key and the hub trust bundle (signed requests to and from rekuest, no shared secrets).")
