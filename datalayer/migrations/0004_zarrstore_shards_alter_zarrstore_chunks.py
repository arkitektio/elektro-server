# Ported from mikro's datalayer 0003 on 2026-09-18: elektro writes sharded zarr now.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('datalayer', '0003_sparsestore_parquetstore_columns'),
    ]

    operations = [
        migrations.AddField(
            model_name='zarrstore',
            name='shards',
            field=models.JSONField(blank=True, help_text='The shard (outer storage object) shape when the array uses zarr v3 sharding_indexed; null for unsharded arrays. When set, `chunks` holds the inner chunk shape.', null=True),
        ),
        migrations.AlterField(
            model_name='zarrstore',
            name='chunks',
            field=models.JSONField(blank=True, help_text="The effective inner chunk shape of the Zarr array — the unit a reader can decode. For sharded arrays this is the sharding codec's inner chunk shape, not the chunk grid's.", null=True),
        ),
    ]
