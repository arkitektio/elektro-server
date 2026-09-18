"""A recording or stimulus site is part of a neuron model: it names the model, required.

No default and no backfill: a site whose model cannot be named is not carried over. On a
database with site rows the NOT NULL column cannot be added -- reset it (the lab was, by
decision) rather than inventing a model for those rows.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_layer_kinds_heatmap_series_waveform_point"),
    ]

    operations = [
        migrations.AddField(
            model_name="recordingsite",
            name="model",
            field=models.ForeignKey(
                help_text="The neuron model this site is part of: the model whose cell, section and position it names",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="recording_sites",
                to="core.neuronmodel",
            ),
        ),
        migrations.AddField(
            model_name="stimulussite",
            name="model",
            field=models.ForeignKey(
                help_text="The neuron model this site is part of: the model whose cell, section and position it names",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="stimulus_sites",
                to="core.neuronmodel",
            ),
        ),
        migrations.AlterField(
            model_name="recordingsite",
            name="cell",
            field=models.CharField(blank=True, help_text="The id of the cell, one of the cells the site's neuron model declares", max_length=1000, null=True),
        ),
        migrations.AlterField(
            model_name="recordingsite",
            name="location",
            field=models.CharField(blank=True, help_text="The id of the section, one of the sections of that cell of the site's neuron model", max_length=1000, null=True),
        ),
        migrations.AlterField(
            model_name="stimulussite",
            name="cell",
            field=models.CharField(blank=True, help_text="The id of the cell, one of the cells the site's neuron model declares", max_length=1000, null=True),
        ),
        migrations.AlterField(
            model_name="stimulussite",
            name="location",
            field=models.CharField(blank=True, help_text="The id of the section, one of the sections of that cell of the site's neuron model", max_length=1000, null=True),
        ),
    ]
