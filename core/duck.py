from contextvars import ContextVar
from functools import cached_property
import boto3
from django.conf import settings
import dataclasses
from strawberry.extensions import SchemaExtension
import duckdb

from django.conf import settings



current_duckdb: ContextVar = ContextVar("duckdb", default=None)


class DuckLayer:

    @cached_property
    def connection(self) -> boto3.Session:
        """ Get a boto3 session for S3 without s3v4 signature"""


        secret_query = f"""
        CREATE SECRET secret1 (
            TYPE S3,
            KEY_ID '{settings.AWS_ACCESS_KEY_ID}',
            SECRET '{settings.AWS_SECRET_ACCESS_KEY}',
            REGION '{settings.AWS_S3_REGION_NAME}',
            ENDPOINT 'minio:9000',
            USE_SSL false,
            URL_STYLE 'path'
        );
        """

        print(secret_query)
                                
                         
                         
        
        x = duckdb.connect()
        x.execute(secret_query)
        return x
    

    def with_table(self, table ,table_name: str = "table1"):
        

        self.connection.execute(f"CREATE TABLE {table_name} (a INTEGER, b VARCHAR);")
        return self
    






def get_current_duck() -> DuckLayer:
    return DuckLayer()
    


class DuckExtension(SchemaExtension):

    def on_operation(self):
        t1 = current_duckdb.set(
            DuckLayer()
        )
        
        yield
        current_duckdb.reset(t1)

        print("GraphQL operation end")
