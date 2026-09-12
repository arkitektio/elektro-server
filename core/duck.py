from contextvars import ContextVar
from urllib.parse import urlparse
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


        # The endpoint comes from the configured datalayer, not a literal: the host moved from
        # `minio` to `rustfs` and a hardcoded name resolves to nothing, so every parquet read
        # failed the HEAD with a DNS error. `netloc` (not `hostname`) because DuckDB's ENDPOINT
        # wants host:port bare -- no scheme, and dropping the port sends it to :80. USE_SSL is
        # read off the parsed scheme rather than `settings.AWS_S3_USE_SSL`, which is hardcoded
        # True while the datalayer speaks plain http.
        parsed = urlparse(settings.AWS_S3_ENDPOINT_URL)
        use_ssl = "true" if parsed.scheme == "https" else "false"

        secret_query = f"""
        CREATE SECRET secret1 (
            TYPE S3,
            KEY_ID '{settings.AWS_ACCESS_KEY_ID}',
            SECRET '{settings.AWS_SECRET_ACCESS_KEY}',
            REGION '{settings.AWS_S3_REGION_NAME}',
            ENDPOINT '{parsed.netloc}',
            USE_SSL {use_ssl},
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
