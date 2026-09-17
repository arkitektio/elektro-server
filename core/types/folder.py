"""The two organisational types: a raw `File`, and the `Folder` things are filed in.

**Vendored from mikro** (``mikro/core/types/folder.py``). A folder here files array
datasets, annotation collections, files and recording sessions (blocks); both types mix in
``OrgScoped``, as every type of this service does.
"""

import datetime
import logging
from typing import TYPE_CHECKING, Annotated, List, Optional, cast

import kante
import strawberry
from kante.types import Info
from strawberry import auto

from core import enums, filters, models, order
from core.types._shared import OrgScoped, apply_link_filters
from core.types.auth import Organization, ProvenanceEntry, Task, User
from datalayer.types import BigFileStore

if TYPE_CHECKING:
    # Runtime imports here would cycle: each of these modules imports this one back.
    from core.types import Block
    from core.types.annotation import AnnotationCollection
    from core.types.array_dataset import ArrayDataset
    from core.types.file_link import FileLink

logger = logging.getLogger(__name__)


@kante.django_type(
    models.File,
    filters=filters.FileFilter,
    pagination=True,
    federated=True,
    ordering=order.FileOrder,
    description="A file in its original format (e.g. an ABF, an NWB file, a vendor recording), stored in a BigFileStore. Files are the raw bytes that array datasets are converted from.",
)
class File(OrgScoped):
    id: auto
    name: auto
    store: BigFileStore

    @kante.django_field(
        description=(
            "The containers converted out of this file: the datasets a converter wrote from it, one per series. **Not a derivation** -- a file has no coordinate system, so these "
            "links claim no geometry and place nothing; they say only that this file's bytes and that data are the same thing"
        ),
        prefetch_related=["links__file"],
    )
    def derived_containers(self, info: Info, filters: filters.FileLinkFilter | None = strawberry.UNSET) -> List[Annotated["FileLink", strawberry.lazy("core.types.file_link")]]:
        """The links naming this file as a source."""
        return apply_link_filters(self.links.filter(direction=enums.FileLinkDirectionChoices.SOURCE.value).order_by("pk"), filters, info)

    @kante.django_field(
        description="The containers this file was written from: the dataset exported to NWB, the annotation collection written to a CSV of events. The mirror of `derivedContainers`",
        prefetch_related=["links__file"],
    )
    def exported_from(self, info: Info, filters: filters.FileLinkFilter | None = strawberry.UNSET) -> List[Annotated["FileLink", strawberry.lazy("core.types.file_link")]]:
        """The links naming this file as a rendition."""
        return apply_link_filters(self.links.filter(direction=enums.FileLinkDirectionChoices.RENDITION.value).order_by("pk"), filters, info)

    provenance_entries: List["ProvenanceEntry"] = kante.django_field(description="Provenance entries for this file")
    creator: User = kante.django_field(description="The user who created this file")
    created_through: Optional[Task] = kante.django_field(description="The task this file was created through, if any")
    created_through_by: Optional[User] = kante.django_field(description="The assigner of the creating task, if any")
    organization: Organization = kante.django_field(description="The organization this file belongs to")
    size: float | None = kante.django_field(description="The size of the file in bytes")
    content_type: str | None = kante.django_field(description="The content type of the file")
    folder: Optional["Folder"] = kante.django_field(description="The folder this file is filed in")
    blocks: List[Annotated["Block", strawberry.lazy("core.types")]] = kante.django_field(description="The recording sessions read from this file")


@kante.django_type(
    models.Folder,
    filters=filters.FolderFilter,
    ordering=order.FolderOrder,
    pagination=True,
    description="A folder is a collection of the things elektro stores. It mimics a folder in a file system and is the top-level container for organising data.",
)
class Folder(OrgScoped):
    id: auto
    files: List["File"]
    # The two containers `FileLink` calls "a thing holding data", and the recording sessions
    # that interpret them. Being in a folder says nothing about where any of them sit in time.
    array_datasets: List[Annotated["ArrayDataset", strawberry.lazy("core.types.array_dataset")]] = kante.django_field(description="The array datasets filed in this folder")
    annotation_collections: List[Annotated["AnnotationCollection", strawberry.lazy("core.types.annotation")]] = kante.django_field(description="The annotation collections filed in this folder")
    blocks: List[Annotated["Block", strawberry.lazy("core.types")]] = kante.django_field(description="The recording sessions filed in this folder")
    parent: Optional["Folder"]
    children: List["Folder"]
    description: str | None
    name: str
    provenance_entries: List["ProvenanceEntry"] = kante.django_field(description="Provenance entries for this folder")
    is_default: bool
    created_at: datetime.datetime
    creator: User | None
    created_through: Optional[Task] = kante.django_field(description="The task this folder was created through, if any")
    created_through_by: Optional[User] = kante.django_field(description="The assigner of the creating task, if any")

    @kante.django_field()
    def pinned(self, info: Info) -> bool:
        return cast(models.Folder, self).pinned_by.filter(id=info.context.request.user.id).exists()

    @kante.django_field()
    def tags(self, info: Info) -> list[str]:
        return cast(models.Folder, self).tags.slugs()
