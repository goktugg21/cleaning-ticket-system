from django.db import migrations


def backfill_contact_building_links(apps, schema_editor):
    """
    Sprint 12B — seed ContactBuildingLink from the legacy single-building
    Contact.building anchor. For every Contact that still points at a
    building, ensure a matching link row exists. Idempotent via
    get_or_create so re-running (e.g. after a partial apply) is safe.
    """
    Contact = apps.get_model("customers", "Contact")
    ContactBuildingLink = apps.get_model("customers", "ContactBuildingLink")

    for contact in Contact.objects.filter(building_id__isnull=False).iterator():
        ContactBuildingLink.objects.get_or_create(
            contact_id=contact.id,
            building_id=contact.building_id,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0008_contactbuildinglink_contact_contact_type_and_more"),
    ]

    operations = [
        migrations.RunPython(
            backfill_contact_building_links,
            migrations.RunPython.noop,
        ),
    ]
