from core.render.enums import RenderNodeKind
from core.render.inputs import models
from strawberry.experimental import pydantic
from strawberry import LazyType
from typing import Optional

@pydantic.input(models.TreeNodeInputModel)
class TreeNodeInput:
    """A Return Widget is a UI element that is used to display the value of a port.

    Return Widgets get displayed both if we show the return values of an assignment,
    but also when we inspect the given arguments of a previous run task. Their primary
    usecase is to adequately display the value of a port, in a user readable way.

    Return Widgets are often overwriten by the underlying UI framework (e.g. Orkestrator)
    to provide a better user experience. For example, a return widget that displays a
    date could be overwriten to display a calendar widget.

    Return Widgets provide more a way to customize this overwriten behavior.

    """
    kind: RenderNodeKind
    label: str | None = None
    context: str | None = None
    gap: int | None = None
    children: Optional[list[LazyType["TreeNodeInput", __name__]]] = None



@pydantic.input(models.TreeInputModel)
class TreeInput:

    id: str | None = "root"
    children: list[TreeNodeInput]


@pydantic.input(models.RenderTreeInputModel)
class RenderTreeInput:
    tree: TreeInput
    name: str