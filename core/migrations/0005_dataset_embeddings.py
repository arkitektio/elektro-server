"""Array, table and sparse datasets embed their name + description (pgvector) for the semantic ``search``.

``VectorExtension`` creates ``vector`` in this database. Like ``CreateExtension('cube')`` in
0001 it is not something ``makemigrations`` can emit -- re-add it by hand if this history is
ever regenerated -- and, like it, the test suite never runs it (schema is built with
run-syncdb; ``tests/conftest.py`` installs the extension itself). It only runs on a real
``migrate``: a no-op where the daten init script already created it, a loud failure on a
daten image without pgvector, which is the right place to fail.

The backfill embeds every existing row in this transaction. That is cheap (a static model,
~1 ms a row) and means search works the moment the release is up; the in-process healer
(``embeddings.healer``, started from ``elektro_server/asgi.py``) would otherwise do it within a
sweep. No historical-model operations: the columns are excluded from provenance history.
"""

from typing import Any

import pgvector.django.vector
from django.conf import settings
from django.db import migrations, models
from pgvector.django import VectorExtension

BATCH = 500
EMBEDDED = ("ArrayDataset", "TableDataset", "SparseDataset")


def backfill_embeddings(apps: Any, schema_editor: Any) -> None:
    """Embed every dataset that has text, with the configured model; no-op when disabled."""
    from embeddings import engine

    if not engine.enabled():
        return
    current = engine.model_id()
    for model_name in EMBEDDED:
        model = apps.get_model("core", model_name)
        queryset = model.objects.exclude(embedding_model=current).order_by("pk").only("pk", "name", "description")
        while True:
            rows = list(queryset[:BATCH])
            if not rows:
                break
            sources = [engine.source_text(row.name, row.description) for row in rows]
            vectors = iter(engine.embed_texts([source for source in sources if source is not None]))
            for row, source in zip(rows, sources, strict=True):
                row.embedding = next(vectors) if source is not None else None
                row.embedding_model = current
            model.objects.bulk_update(rows, ["embedding", "embedding_model"])


class Migration(migrations.Migration):
    """Extension, the columns on three models, the healer's indexes, and the backfill."""

    dependencies = [
        ("authentikate", "0006_alter_app_identifier_alter_release_unique_together"),
        ("core", "0004_simulation_is_a_spoke"),
        ("datalayer", "0004_zarrstore_shards_alter_zarrstore_chunks"),
        ("koherent", "0003_rename_assignation_to_task"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        VectorExtension(),
        migrations.AddField(
            model_name="arraydataset",
            name="embedding",
            field=pgvector.django.vector.VectorField(blank=True, dimensions=256, editable=False, help_text="Unit-length embedding of name + description, by the model named in embedding_model; NULL when there is no text to embed", null=True),
        ),
        migrations.AddField(
            model_name="arraydataset",
            name="embedding_model",
            field=models.CharField(blank=True, default="", editable=False, help_text="The embedding model that produced `embedding`. Rows whose value differs from the configured model are re-embedded in-process and are excluded from vector search until then", max_length=200),
        ),
        migrations.AddField(
            model_name="sparsedataset",
            name="embedding",
            field=pgvector.django.vector.VectorField(blank=True, dimensions=256, editable=False, help_text="Unit-length embedding of name + description, by the model named in embedding_model; NULL when there is no text to embed", null=True),
        ),
        migrations.AddField(
            model_name="sparsedataset",
            name="embedding_model",
            field=models.CharField(blank=True, default="", editable=False, help_text="The embedding model that produced `embedding`. Rows whose value differs from the configured model are re-embedded in-process and are excluded from vector search until then", max_length=200),
        ),
        migrations.AddField(
            model_name="tabledataset",
            name="embedding",
            field=pgvector.django.vector.VectorField(blank=True, dimensions=256, editable=False, help_text="Unit-length embedding of name + description, by the model named in embedding_model; NULL when there is no text to embed", null=True),
        ),
        migrations.AddField(
            model_name="tabledataset",
            name="embedding_model",
            field=models.CharField(blank=True, default="", editable=False, help_text="The embedding model that produced `embedding`. Rows whose value differs from the configured model are re-embedded in-process and are excluded from vector search until then", max_length=200),
        ),
        migrations.AddIndex(
            model_name="arraydataset",
            index=models.Index(fields=["embedding_model"], name="array_dataset_emb_model_idx"),
        ),
        migrations.AddIndex(
            model_name="sparsedataset",
            index=models.Index(fields=["embedding_model"], name="sparse_dataset_emb_model_idx"),
        ),
        migrations.AddIndex(
            model_name="tabledataset",
            index=models.Index(fields=["embedding_model"], name="table_dataset_emb_model_idx"),
        ),
        migrations.RunPython(backfill_embeddings, migrations.RunPython.noop),
    ]
