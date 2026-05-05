from django.test import SimpleTestCase

from config.security import get_production_settings_errors


def production_settings(**overrides):
    settings = {
        "DEBUG": False,
        "SECRET_KEY": "x" * 60,
        "ALLOWED_HOSTS": ["example.com"],
        "CORS_ALLOWED_ORIGINS": ["https://example.com"],
        "CSRF_TRUSTED_ORIGINS": ["https://example.com"],
        "DATABASES": {"default": {"PASSWORD": "very-strong-db-password"}},
        "REST_FRAMEWORK": {
            "DEFAULT_THROTTLE_RATES": {
                "anon": "60/minute",
                "user": "5000/hour",
                "auth_token": "20/minute",
                "auth_token_refresh": "60/minute",
            }
        },
    }
    settings.update(overrides)
    return settings


class ProductionSettingsValidatorTests(SimpleTestCase):
    def assert_has_error(self, settings, expected):
        errors = get_production_settings_errors(settings)
        self.assertTrue(
            any(expected in error for error in errors),
            f"Expected {expected!r} in {errors!r}",
        )

    def test_safe_production_settings_pass(self):
        self.assertEqual(get_production_settings_errors(production_settings()), [])

    def test_missing_secret_key_in_prod_raises(self):
        self.assert_has_error(production_settings(SECRET_KEY=""), "DJANGO_SECRET_KEY")

    def test_placeholder_secret_key_in_prod_raises(self):
        self.assert_has_error(
            production_settings(SECRET_KEY="change-me-generate-a-long-random-secret"),
            "DJANGO_SECRET_KEY",
        )

    def test_missing_allowed_hosts_in_prod_raises(self):
        self.assert_has_error(production_settings(ALLOWED_HOSTS=[]), "DJANGO_ALLOWED_HOSTS")

    def test_wildcard_allowed_hosts_in_prod_raises(self):
        self.assert_has_error(production_settings(ALLOWED_HOSTS=["*"]), "DJANGO_ALLOWED_HOSTS")

    def test_missing_cors_origins_in_prod_raises(self):
        self.assert_has_error(production_settings(CORS_ALLOWED_ORIGINS=[]), "CORS_ALLOWED_ORIGINS")

    def test_missing_csrf_trusted_origins_in_prod_raises(self):
        self.assert_has_error(production_settings(CSRF_TRUSTED_ORIGINS=[]), "CSRF_TRUSTED_ORIGINS")

    def test_insecure_throttle_defaults_in_prod_raise(self):
        settings = production_settings(
            REST_FRAMEWORK={
                "DEFAULT_THROTTLE_RATES": {
                    "anon": "1000/minute",
                    "user": "10000/hour",
                    "auth_token": "200/minute",
                    "auth_token_refresh": "300/minute",
                }
            }
        )
        self.assert_has_error(settings, "auth_token")

    def test_weak_database_password_in_prod_raises(self):
        self.assert_has_error(
            production_settings(DATABASES={"default": {"PASSWORD": "cleaning_ticket_password"}}),
            "POSTGRES_PASSWORD",
        )
