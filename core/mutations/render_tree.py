from kante.types import Info
import strawberry
from core import types, models, enums
from django.conf import settings
from strawberry.file_uploads import Upload
from core.render.inputs.types import RenderTreeInput


def traverse_context_tree(tree, collection: list[str]):
    if getattr(tree, "context", None) is not None:
        collection.append(tree.context)

    if tree.children is None:
        return
    for child in tree.children:
        

        traverse_context_tree(child, collection)


def create_render_tree(
    info: Info,
    input: RenderTreeInput,
) -> types.RenderTree:
    


    collection = []

    traverse_context_tree(input.tree, collection)


    contexts = models.RGBRenderContext.objects.filter(id__in=collection)

    context = models.RenderTree.objects.create(
        name=input.name,
        tree=strawberry.asdict(input.tree)

    )

    context.linked_contexts.set(contexts)

    

    return context

