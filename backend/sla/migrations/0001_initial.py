"""Sprint W4-Q §2 — the FIRST migration `sla` has ever had.

The app has been live since Sprint 7 with no models at all: the engine
writes `Ticket.sla_status` and keeps its arithmetic pure. This adds one
configuration table and touches nothing the engine reads, so it is
additive in the strongest sense — no existing column changes, no data is
backfilled, and every column on the new table is nullable.

That nullability IS the migration story for existing deployments. No
company gets a row, every NULL falls back to `settings.SLA_WARN_*`, and
the sweep resolves exactly the numbers it resolved to yesterday. The env
vars become the fallback the moment somebody saves a number, and only
for the fields they filled in.
"""


import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('companies', '0005_company_logo'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SlaWarningThreshold',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('approval_cutoff_days', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('approval_cutoff_escalate_days', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('manager_review_business_hours', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('manager_review_escalate_business_hours', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('not_started_business_hours', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('not_started_escalate_business_hours', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('cooldown_hours', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='sla_warning_threshold', to='companies.company')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'SLA warning threshold',
                'verbose_name_plural': 'SLA warning thresholds',
            },
        ),
    ]
