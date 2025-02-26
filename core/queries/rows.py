
from core import models, types, enums, filters as f, pagination as p, scalars
import strawberry
from typing import Union
from itertools import chain
from core.duck import get_current_duck



def rows(info, table: strawberry.ID, filters: f.RowFilter | None = None, pagination: p.TablePaginationInput | None = None) -> list[scalars.MetricMap]:
    if filters is None:
        filters = f.RowFilter()
    if pagination is None:
        pagination = p.TablePaginationInput()


    table = models.Table.objects.get(id=table)

    print("xxx")
    x = get_current_duck()


    sql =  f"""
        SELECT * FROM {table.store.duckdb_string}
    """

    if filters.clause:
        sql += f"""
        {filters.clause}
        """

    sql += f"""
        LIMIT {pagination.limit}
        OFFSET {pagination.offset};
    """


    print(sql)
    



    result = x.connection.sql(sql).df()
    
    return result.to_dict(orient='records')


