# Definition
import strawberry
from graphql.language import DirectiveLocation
from asgiref.sync import sync_to_async


@strawberry.directive(
    locations=[DirectiveLocation.FIELD], description="Make string uppercase"
)
def upper(value: str):
    return value.upper()


@strawberry.directive(
    locations=[DirectiveLocation.FIELD], description="Make get stuff uppercase"
)
async def relation(value: str, on: str):
    return await sync_to_async(value.filter)(descend_links__assignation_id=on)


@strawberry.directive(locations=[DirectiveLocation.FIELD])
def replace(value: str, old: str, new: str):
    return value.replace(old, new)
