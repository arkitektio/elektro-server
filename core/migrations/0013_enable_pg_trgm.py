from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    """Enable the ``pg_trgm`` extension powering fuzzy / trigram search.

    Used by ``core.filters.SearchFilterMixin`` for typo-tolerant matching
    (``__trigram_similar`` lookups and ``TrigramSimilarity`` ranking).
    """

    dependencies = [
        ("core", "0012_blocksegment_end_time_blocksegment_start_time_and_more"),
    ]

    operations = [
        TrigramExtension(),
    ]
