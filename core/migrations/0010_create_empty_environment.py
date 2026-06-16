from django.db import migrations


def create_empty_environment(apps, schema_editor):
    """Backfill NeuronModel rows that have no environment.

    NeuronModel.environment is about to become NOT NULL, so every existing row
    with a NULL environment needs one. We mint an "Empty Environment" per
    organization (degrades to a single env when the deployment is single-org)
    and attach each orphan model to the empty env of its creator's organization,
    falling back to the first organization when the creator/org can't be resolved.
    """
    ModEnvironment = apps.get_model("core", "ModEnvironment")
    NeuronModel = apps.get_model("core", "NeuronModel")
    Organization = apps.get_model("authentikate", "Organization")
    Membership = apps.get_model("authentikate", "Membership")

    orphans = NeuronModel.objects.filter(environment__isnull=True)
    if not orphans.exists():
        return

    fallback_org = Organization.objects.order_by("id").first()
    if fallback_org is None:
        raise RuntimeError(
            "Cannot backfill NeuronModel.environment: no Organization exists to own the empty environment."
        )

    empty_by_org = {}

    def empty_env_for(org):
        if org.id not in empty_by_org:
            env, _ = ModEnvironment.objects.get_or_create(
                organization=org,
                name="Empty Environment",
                defaults={
                    "description": "Auto-created for neuron models that had no environment.",
                },
            )
            empty_by_org[org.id] = env
        return empty_by_org[org.id]

    for nm in orphans.iterator():
        org = None
        if nm.creator_id:
            membership = Membership.objects.filter(user_id=nm.creator_id).order_by("id").first()
            if membership is not None:
                org = membership.organization
        if org is None:
            org = fallback_org
        nm.environment = empty_env_for(org)
        nm.save(update_fields=["environment"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_remove_historicalanalogsignal_assignation_id_and_more"),
    ]

    operations = [
        migrations.RunPython(create_empty_environment, migrations.RunPython.noop),
    ]
