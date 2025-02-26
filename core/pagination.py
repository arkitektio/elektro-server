import strawberry


@strawberry.input
class TablePaginationInput:
    limit: int | None = 200
    offset: int | None = 0


@strawberry.input
class ChildrenPaginationInput:
    limit: int | None = 200
    offset: int | None = 0