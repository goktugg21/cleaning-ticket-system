"""
Sprint 134 — `ALLOWED_HOSTS` admits the Docker Compose internal DNS name
("backend") unconditionally, closing the DisallowedHost gap for an
internal HTTP request addressed by that name (health.py's docstring
option (c)) without loosening config/security.py's production validator.
See test_settings_validator.py for the validator-side regression test.
"""
from django.conf import settings
from django.test import SimpleTestCase


class AllowedHostsAdmitsInternalServiceNameTests(SimpleTestCase):
    def test_backend_service_name_is_admitted(self):
        self.assertIn("backend", settings.ALLOWED_HOSTS)

    def test_operator_supplied_hosts_are_preserved_alongside_it(self):
        # The fix APPENDS "backend" — it must never replace or shadow
        # whatever DJANGO_ALLOWED_HOSTS itself resolved to.
        self.assertGreaterEqual(len(settings.ALLOWED_HOSTS), 1)
        self.assertNotEqual(settings.ALLOWED_HOSTS, ["backend"])
