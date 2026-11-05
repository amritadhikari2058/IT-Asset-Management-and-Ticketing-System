"""Tests for P2 operational diagnostic management commands.

All tests are configuration/mock-based: no live SMTP, IMAP, Redis, or
PostgreSQL connectivity is required.
"""

import sys
import imaplib
from io import StringIO
from unittest.mock import patch, MagicMock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


class ValidateProductionConfigTests(TestCase):
    """Tests for validate_production_config (normal and strict modes)."""

    def _base_overrides(self):
        return {
            "DEBUG": False,
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%",
            "ALLOWED_HOSTS": ["example.com", "www.example.com"],
            "CSRF_TRUSTED_ORIGINS": ["https://example.com"],
            "CORS_ALLOWED_ORIGINS": ["https://example.com"],
            "SESSION_COOKIE_SECURE": True,
            "CSRF_COOKIE_SECURE": True,
            "SECURE_SSL_REDIRECT": True,
            "SECURE_HSTS_SECONDS": 31536000,
            "DATABASES": {
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "ticketing_prod",
                    "HOST": "db.example.com",
                    "PORT": 5432,
                    "USER": "ticketing",
                    "PASSWORD": "secret",
                }
            },
            "SIMPLE_JWT": {
                "ACCESS_TOKEN_LIFETIME": __import__("datetime").timedelta(minutes=60),
                "REFRESH_TOKEN_LIFETIME": __import__("datetime").timedelta(days=1),
                "BLACKLIST_ENABLED": True,
            },
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": "smtp.example.com",
            "EMAIL_HOST_USER": "user@example.com",
            "EMAIL_HOST_PASSWORD": "secret",
            "EMAIL_PORT": 587,
            "EMAIL_USE_TLS": True,
            "EMAIL_USE_SSL": False,
            "EMAIL_TIMEOUT": 10,
            "DEFAULT_FROM_EMAIL": "noreply@example.com",
            "STORAGE_BACKEND": "local",
            "CELERY_BROKER_URL": "redis://localhost:6379/0",
            "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
            "CELERY_TASK_ALWAYS_EAGER": False,
            "CELERY_TASK_SERIALIZER": "json",
            "CELERY_ACCEPT_CONTENT": ["json"],
            "CELERY_TASK_TIME_LIMIT": 300,
            "CELERY_BEAT_SCHEDULE": {
                "sla": {"task": "tickets.tasks.check_sla_escalations"},
                "maintenance": {"task": "assets.tasks.check_maintenance_reminders"},
                "inbound": {"task": "common.tasks.process_inbound_mailbox"},
                "reports": {"task": "common.tasks.run_scheduled_reports"},
            },
            "INBOUND_MAILBOX_ENABLED": True,
            "INBOUND_MAILBOX_HOST": "imap.example.com",
            "INBOUND_MAILBOX_USER": "user@example.com",
            "INBOUND_MAILBOX_PASSWORD": "secret",
            "ATTACHMENT_MAX_SIZE_MB": 10,
        }

    def _run(self, strict=False, **overrides):
        """Run the command with given settings overrides, capture output."""
        merged = self._base_overrides()
        merged.update(overrides)
        out = StringIO()
        err = StringIO()
        with override_settings(**merged):
            try:
                call_command(
                    "validate_production_config",
                    strict=strict,
                    stdout=out, stderr=err,
                )
            except SystemExit as exc:
                return exc.code, out.getvalue(), err.getvalue()
        return None, out.getvalue(), err.getvalue()

    def test_valid_config_normal_mode_exits_zero(self):
        code, out, _ = self._run(strict=False)
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)
        self.assertIn("Configuration validation complete", out)

    def test_valid_config_strict_mode_exits_zero(self):
        code, out, _ = self._run(strict=True)
        self.assertEqual(code, 0)

    def test_strict_mode_sqlite_is_error(self):
        code, out, _ = self._run(
            strict=True,
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3",
                                   "NAME": ":memory:"}},
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)
        self.assertIn("SQLite", out)

    def test_debug_true_normal_mode_is_warning(self):
        code, out, _ = self._run(
            strict=False,
            DEBUG=True,
        )
        self.assertEqual(code, 0)  # warnings allowed in normal mode
        self.assertIn("WARNING", out)
        self.assertIn("DEBUG", out)

    def test_debug_true_strict_mode_is_error(self):
        code, out, _ = self._run(
            strict=True,
            DEBUG=True,
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)

    def test_placeholder_secret_key_normal_warning(self):
        code, out, _ = self._run(
            strict=False,
            SECRET_KEY="django-insecure-abc",
        )
        self.assertEqual(code, 0)
        self.assertIn("WARNING", out)
        self.assertIn("SECRET_KEY", out)

    def test_placeholder_secret_key_strict_error(self):
        code, out, _ = self._run(
            strict=True,
            SECRET_KEY="django-insecure-abc",
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)

    def test_short_secret_key_strict_error(self):
        code, out, _ = self._run(
            strict=True,
            SECRET_KEY="short",
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)
        # Secret value itself must not appear in output
        self.assertNotIn("short", out.split("SECRET_KEY")[0])

    def test_missing_allowed_hosts_strict_error(self):
        code, out, _ = self._run(
            strict=True,
            ALLOWED_HOSTS=[],
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)

    def test_wildcard_only_allowed_hosts_warning(self):
        code, out, _ = self._run(
            strict=False,
            ALLOWED_HOSTS=["*"],
        )
        self.assertEqual(code, 0)
        self.assertIn("WARNING", out)
        self.assertIn("wildcard", out)

    def test_console_email_backend_normal_warning(self):
        code, out, _ = self._run(
            strict=False,
            EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        )
        self.assertEqual(code, 0)
        self.assertIn("WARNING", out)

    def test_console_email_backend_strict_error(self):
        code, out, _ = self._run(
            strict=True,
            EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)

    def test_tls_and_ssl_both_enabled_strict_error(self):
        code, out, _ = self._run(
            strict=True,
            EMAIL_USE_TLS=True,
            EMAIL_USE_SSL=True,
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)

    def test_missing_redis_broker_strict_error(self):
        code, out, _ = self._run(
            strict=True,
            CELERY_BROKER_URL="",
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)
        self.assertIn("BROKER", out)

    def test_unsafe_celery_content_pickle_strict_error(self):
        code, out, _ = self._run(
            strict=True,
            CELERY_ACCEPT_CONTENT=["json", "pickle"],
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)
        self.assertIn("pickle", out)

    def test_missing_beat_task_strict_error(self):
        code, out, _ = self._run(
            strict=True,
            CELERY_BEAT_SCHEDULE={},
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)
        self.assertIn("beat", out.lower())

    def test_imap_enabled_missing_values_warning(self):
        code, out, _ = self._run(
            strict=False,
            INBOUND_MAILBOX_ENABLED=True,
            INBOUND_MAILBOX_HOST="",
            INBOUND_MAILBOX_USER="",
        )
        self.assertEqual(code, 0)
        self.assertIn("WARNING", out)

    def test_s3_missing_bucket_strict_error(self):
        code, out, _ = self._run(
            strict=True,
            STORAGE_BACKEND="s3",
            AWS_STORAGE_BUCKET_NAME="",
            AWS_S3_REGION_NAME="",
        )
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)
        self.assertIn("bucket", out)

    def test_secrets_not_in_output(self):
        code, out, _ = self._run(
            strict=False,
            CELERY_BROKER_URL="redis://user:pass@localhost:6379/0",
            EMAIL_HOST_PASSWORD="smtp-secret",
        )
        self.assertEqual(code, 0)
        self.assertNotIn("user:pass", out)
        self.assertNotIn("smtp-secret", out)

    def test_normal_mode_no_errors_exits_zero(self):
        code, out, _ = self._run(strict=False)
        self.assertEqual(code, 0)


class CheckRedisTests(TestCase):
    """Tests for check_redis (mocked)."""

    @patch("common.management.commands.check_redis.redis_lib")
    def test_redis_ping_success(self, mock_redis):
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis.Redis.return_value = mock_client

        out = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("check_redis", "--timeout", "3", "--url",
                         "redis://localhost:6379/0", stdout=out)
        self.assertEqual(ctx.exception.code, 0)
        self.assertTrue(mock_client.ping.called)

    @patch("common.management.commands.check_redis.redis_lib")
    def test_redis_connection_failure(self, mock_redis):
        mock_client = MagicMock()
        mock_client.ping.side_effect = ConnectionError("refused")
        mock_redis.Redis.return_value = mock_client

        out = StringIO()
        err = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("check_redis", "--url", "redis://localhost:6379/0",
                         stdout=out, stderr=err)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("ERROR", err.getvalue())

    def test_redis_no_broker_url(self):
        with override_settings(CELERY_BROKER_URL=""):
            out = StringIO()
            err = StringIO()
            with self.assertRaises(SystemExit) as ctx:
                call_command("check_redis", stdout=out, stderr=err)
            self.assertEqual(ctx.exception.code, 1)
            self.assertIn("not configured", err.getvalue())


class CheckCeleryConfigTests(TestCase):
    """Tests for check_celery_config (mocked)."""

    def _run(self, **overrides):
        out = StringIO()
        err = StringIO()
        with override_settings(**overrides):
            try:
                call_command("check_celery_config", stdout=out, stderr=err)
            except SystemExit as exc:
                return exc.code, out.getvalue(), err.getvalue()
        return None, out.getvalue(), err.getvalue()

    def test_valid_config(self):
        code, out, _ = self._run(
            CELERY_BROKER_URL="redis://localhost:6379/0",
            CELERY_RESULT_BACKEND="redis://localhost:6379/0",
            CELERY_TASK_ALWAYS_EAGER=False,
            CELERY_TASK_SERIALIZER="json",
            CELERY_ACCEPT_CONTENT=["json"],
            CELERY_TASK_TIME_LIMIT=300,
            CELERY_BEAT_SCHEDULE={
                "sla": {"task": "tickets.tasks.check_sla_escalations"},
                "maintenance": {"task": "assets.tasks.check_maintenance_reminders"},
                "inbound": {"task": "common.tasks.process_inbound_mailbox"},
                "reports": {"task": "common.tasks.run_scheduled_reports"},
            },
        )
        self.assertEqual(code, 0)

    def test_missing_broker(self):
        code, _, err = self._run(CELERY_BROKER_URL="")
        self.assertEqual(code, 1)
        self.assertIn("BROKER_URL", err)

    def test_pickle_accept_content(self):
        code, _, err = self._run(
            CELERY_BROKER_URL="redis://localhost:6379/0",
            CELERY_ACCEPT_CONTENT=["json", "pickle"],
            CELERY_BEAT_SCHEDULE={},
        )
        self.assertEqual(code, 1)
        self.assertIn("pickle", err)

    def test_missing_beat_task(self):
        code, _, err = self._run(
            CELERY_BROKER_URL="redis://localhost:6379/0",
            CELERY_BEAT_SCHEDULE={"x": {"task": "other.tasks.thing"}},
        )
        self.assertEqual(code, 1)
        self.assertIn("missing", err.lower())


class CheckCeleryWorkerTests(TestCase):
    """Tests for check_celery_worker (mocked)."""

    @patch("celery.current_app")
    def test_worker_responds(self, mock_app):
        mock_inspect = MagicMock()
        mock_inspect.ping.return_value = {"worker1@host": {"ok": True}}
        mock_app.control.inspect.return_value = mock_inspect

        out = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("check_celery_worker", "--timeout", "3",
                         stdout=out)
        self.assertEqual(ctx.exception.code, 0)

    @patch("celery.current_app")
    def test_no_worker_responds(self, mock_app):
        mock_inspect = MagicMock()
        mock_inspect.ping.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        out = StringIO()
        err = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("check_celery_worker", stdout=out, stderr=err)
        self.assertEqual(ctx.exception.code, 1)

    @patch("celery.current_app")
    def test_inspect_failure(self, mock_app):
        mock_app.control.inspect.side_effect = Exception("broker down")

        out = StringIO()
        err = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("check_celery_worker", stdout=out, stderr=err)
        self.assertEqual(ctx.exception.code, 1)


class TestEmailDeliveryTests(TestCase):
    """Tests for test_email_delivery (mocked, no real send)."""

    def _run(self, **kwargs):
        out = StringIO()
        err = StringIO()
        with override_settings(**kwargs.get("settings", {})):
            try:
                call_command("test_email_delivery",
                             *kwargs.get("args", []),
                             stdout=out, stderr=err)
            except SystemExit as exc:
                return exc.code, out.getvalue(), err.getvalue()
        return None, out.getvalue(), err.getvalue()

    def test_dry_run_valid_config(self):
        code, out, _ = self._run(settings={
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": "smtp.example.com",
            "DEFAULT_FROM_EMAIL": "noreply@example.com",
        })
        self.assertEqual(code, 0)
        self.assertIn("Email backend", out)

    def test_dry_run_console_backend_warning(self):
        code, out, _ = self._run(settings={
            "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
        })
        self.assertEqual(code, 0)
        self.assertIn("WARNING", out)

    def test_send_without_to(self):
        out = StringIO()
        err = StringIO()
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            DEFAULT_FROM_EMAIL="noreply@example.com",
        ):
            with self.assertRaises(SystemExit) as ctx:
                call_command("test_email_delivery", "--send",
                             stdout=out, stderr=err)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("requires --to", err.getvalue())

    def test_send_invalid_recipient(self):
        out = StringIO()
        err = StringIO()
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            DEFAULT_FROM_EMAIL="noreply@example.com",
        ):
            with self.assertRaises(SystemExit) as ctx:
                call_command("test_email_delivery", "--send", "--to", "not-an-email",
                             stdout=out, stderr=err)
        self.assertEqual(ctx.exception.code, 2)

    def test_send_missing_sender(self):
        out = StringIO()
        err = StringIO()
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            DEFAULT_FROM_EMAIL="",
        ):
            with self.assertRaises(SystemExit) as ctx:
                call_command("test_email_delivery", "--send", "--to", "a@b.com",
                             stdout=out, stderr=err)
        self.assertEqual(ctx.exception.code, 3)

    @patch("django.core.mail.EmailMessage.send")
    def test_mocked_successful_send(self, mock_send):
        mock_send.return_value = 1
        out = StringIO()
        err = StringIO()
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            EMAIL_HOST="smtp.example.com",
            DEFAULT_FROM_EMAIL="noreply@example.com",
        ):
            with self.assertRaises(SystemExit) as ctx:
                call_command("test_email_delivery", "--send", "--to", "user@example.com",
                             stdout=out, stderr=err)
        self.assertEqual(ctx.exception.code, 0)
        mock_send.assert_called_once()

    @patch("django.core.mail.EmailMessage.send")
    def test_mocked_send_failure(self, mock_send):
        mock_send.side_effect = Exception("SMTP auth failed")
        out = StringIO()
        err = StringIO()
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            EMAIL_HOST="smtp.example.com",
            DEFAULT_FROM_EMAIL="noreply@example.com",
        ):
            with self.assertRaises(SystemExit) as ctx:
                call_command("test_email_delivery", "--send", "--to", "user@example.com",
                             stdout=out, stderr=err)
        self.assertEqual(ctx.exception.code, 4)
        self.assertNotIn("SMTP auth failed", err.getvalue())  # sanitized
        self.assertIn("ERROR", err.getvalue())


class CheckInboundEmailTests(TestCase):
    """Tests for check_inbound_email (mocked IMAP)."""

    def _run(self, connect=False, **overrides):
        out = StringIO()
        err = StringIO()
        args = ["--connect"] if connect else []
        with override_settings(**overrides):
            try:
                call_command("check_inbound_email", *args,
                             stdout=out, stderr=err)
            except SystemExit as exc:
                return exc.code, out.getvalue(), err.getvalue()
        return None, out.getvalue(), err.getvalue()

    def test_configuration_only(self):
        code, out, _ = self._run(
            INBOUND_MAILBOX_ENABLED=True,
            INBOUND_MAILBOX_HOST="imap.example.com",
            INBOUND_MAILBOX_USER="user@example.com",
        )
        self.assertEqual(code, 0)
        self.assertIn("Inbound mailbox enabled: True", out)

    def test_disabled_inbound(self):
        code, out, _ = self._run(INBOUND_MAILBOX_ENABLED=False)
        self.assertEqual(code, 0)
        self.assertIn("disabled", out)

    def test_missing_host_when_enabled(self):
        code, _, err = self._run(
            INBOUND_MAILBOX_ENABLED=True,
            INBOUND_MAILBOX_HOST="",
            INBOUND_MAILBOX_USER="user@example.com",
        )
        self.assertEqual(code, 1)
        self.assertIn("not set", err)

    @patch("common.management.commands.check_inbound_email.imaplib")
    def test_readonly_connect_success(self, mock_imaplib):
        mock_client = MagicMock()
        mock_client.select.return_value = ("OK", [b"5"])
        mock_imaplib.IMAP4_SSL.return_value = mock_client

        code, out, _ = self._run(
            connect=True,
            INBOUND_MAILBOX_ENABLED=True,
            INBOUND_MAILBOX_HOST="imap.example.com",
            INBOUND_MAILBOX_USER="user@example.com",
            INBOUND_MAILBOX_PASSWORD="pass",
            INBOUND_MAILBOX_USE_TLS=True,
        )
        self.assertEqual(code, 0)
        self.assertIn("OK: Read-only IMAP connection", out)
        # Verify SELECT was called with readonly=True
        mock_client.select.assert_called_with("INBOX", readonly=True)
        # Verify login was called (no body fetch, no message mutation)
        mock_client.login.assert_called_once()

    @patch("common.management.commands.check_inbound_email.imaplib")
    def test_connect_auth_failure(self, mock_imaplib):
        mock_client = MagicMock()
        mock_client.login.side_effect = imaplib.IMAP4.error("authentication failed")
        mock_imaplib.IMAP4_SSL.return_value = mock_client

        code, _, err = self._run(
            connect=True,
            INBOUND_MAILBOX_ENABLED=True,
            INBOUND_MAILBOX_HOST="imap.example.com",
            INBOUND_MAILBOX_USER="user@example.com",
            INBOUND_MAILBOX_PASSWORD="pass",
        )
        self.assertEqual(code, 1)
        self.assertIn("authentication", err)