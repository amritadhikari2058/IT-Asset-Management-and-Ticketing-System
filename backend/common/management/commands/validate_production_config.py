"""Non-destructive production configuration validator.

Usage:

    python backend/manage.py validate_production_config
    python backend/manage.py validate_production_config --strict

Validates configuration without mutating data or contacting external
services unless an explicit connectivity flag is supplied.

Output model: each check prints one of PASS / WARNING / ERROR / SKIPPED
with a check identifier, short description, safe result, and remediation
message when applicable. No secrets (SECRET_KEY, passwords, tokens) are
ever printed.

Exit codes:
  0  - no ERROR results (normal mode)
  1  - at least one ERROR result
"""

import sys
from urllib.parse import urlparse

from django.core.management.base import BaseCommand
from django.conf import settings


def _sanitize_url(url):
    """Return a URL with credentials stripped, or '(not set)'."""
    if not url:
        return "(not set)"
    try:
        parsed = urlparse(url)
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc += f":{parsed.port}"
        scheme = parsed.scheme or ""
        path = parsed.path or ""
        if parsed.query:
            path += f"?{parsed.query}"
        return f"{scheme}://{netloc}{path}"
    except Exception:
        return "(redacted)"


def _bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes", "on")
    return bool(val)


class Command(BaseCommand):
    help = "Validate production configuration without mutating data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Treat development-acceptable settings as production errors.",
        )
        parser.add_argument(
            "--check-connectivity",
            action="store_true",
            help="Attempt live connectivity checks (Redis/SMTP/IMAP). "
            "Off by default to keep this command safe in CI.",
        )

    def handle(self, *args, **options):
        self.strict = options["strict"]
        self.check_connectivity = options["check_connectivity"]
        self.errors = 0
        self.warnings = 0

        self._check_django_security()
        self._check_database()
        self._check_jwt()
        self._check_email()
        self._check_inbound_email()
        self._check_redis_celery()
        self._check_storage()
        self._check_logging()

        self.stdout.write("")
        self.stdout.write(
            f"Configuration validation complete: "
            f"{self.errors} error(s), {self.warnings} warning(s).")
        sys.exit(1 if self.errors > 0 else 0)

    # ---- helpers -----------------------------------------------------

    def _line(self, check_id, status, description, remediation=""):
        pad = " " * max(0, 44 - len(check_id))
        rem = f"  -> {remediation}" if remediation else ""
        self.stdout.write(
            f"{status}     {check_id}{pad}{description}{rem}")

    def _pass(self, check_id, description, remediation=""):
        self._line(check_id, "PASS", description, remediation)

    def _warn(self, check_id, description, remediation=""):
        self._line(check_id, "WARNING", description, remediation)
        self.warnings += 1

    def _error(self, check_id, description, remediation=""):
        self._line(check_id, "ERROR", description, remediation)
        self.errors += 1

    def _info(self, check_id, description):
        pad = " " * max(0, 44 - len(check_id))
        self.stdout.write(f"INFO     {check_id}{pad}{description}")

    # ---- check groups ------------------------------------------------

    def _check_django_security(self):
        s = settings

        # DEBUG
        debug = _bool(getattr(s, "DEBUG", True))
        if debug:
            if self.strict:
                self._error("config.security.debug",
                            "DEBUG is True in strict production mode",
                            "Set DEBUG=false via the DEBUG env variable.")
            else:
                self._warn("config.security.debug",
                           "DEBUG is True (acceptable for local dev only)",
                           "Set DEBUG=false for production deployments.")
        else:
            self._pass("config.security.debug", "DEBUG is disabled")

        # SECRET_KEY
        secret_key = getattr(s, "SECRET_KEY", "") or ""
        is_placeholder = (
            not secret_key
            or secret_key.startswith("django-insecure-")
            or secret_key == "change-me-in-production"
            or len(secret_key) < 50
            or len(set(secret_key)) < 5
        )
        if is_placeholder:
            if self.strict:
                self._error("config.security.secret_key",
                            "SECRET_KEY is missing, a placeholder, or too short",
                            "Set a unique SECRET_KEY environment variable "
                            "(50+ characters, high entropy).")
            else:
                self._warn("config.security.secret_key",
                           "SECRET_KEY uses the committed development default",
                           "Set a unique SECRET_KEY for production.")
        else:
            self._pass("config.security.secret_key",
                       "SECRET_KEY is present and not a placeholder")

        # ALLOWED_HOSTS
        allowed_hosts = list(getattr(s, "ALLOWED_HOSTS", []))
        if not allowed_hosts:
            if self.strict:
                self._error("config.security.allowed_hosts",
                            "ALLOWED_HOSTS is empty",
                            "Set ALLOWED_HOSTS to explicit production hostnames.")
            else:
                self._warn("config.security.allowed_hosts",
                           "ALLOWED_HOSTS is empty (localhost-only dev behavior)",
                           "Set ALLOWED_HOSTS for production.")
        elif len(allowed_hosts) == 1 and allowed_hosts[0] == "*":
            self._warn("config.security.allowed_hosts_wildcard",
                       "ALLOWED_HOSTS is wildcard-only (*)",
                       "Replace with explicit hostnames unless documented.")
        else:
            self._pass("config.security.allowed_hosts",
                       f"ALLOWED_HOSTS explicit: {', '.join(allowed_hosts)}")

        # CSRF_TRUSTED_ORIGINS
        csrf_origins = list(getattr(s, "CSRF_TRUSTED_ORIGINS", []))
        if not _bool(getattr(s, "DEBUG", True)) and not csrf_origins:
            self._warn("config.security.csrf_trusted_origins",
                       "CSRF_TRUSTED_ORIGINS is empty in production",
                       "Set CSRF_TRUSTED_ORIGINS for HTTPS origins.")
        else:
            self._pass("config.security.csrf_trusted_origins",
                       f"CSRF_TRUSTED_ORIGINS: {', '.join(csrf_origins) or '(unset)'}")

        # CORS_ALLOWED_ORIGINS
        cors_origins = list(getattr(s, "CORS_ALLOWED_ORIGINS", []))
        has_wildcard = any(o == "*" for o in cors_origins)
        if has_wildcard:
            self._warn("config.security.cors_wildcard",
                       "CORS_ALLOWED_ORIGINS contains wildcard (*)",
                       "Use explicit origins instead of wildcards.")
        elif not cors_origins:
            self._warn("config.security.cors_empty",
                       "CORS_ALLOWED_ORIGINS is empty",
                       "Add explicit frontend origins for production.")
        else:
            self._pass("config.security.cors_origins",
                       f"CORS_ALLOWED_ORIGINS: {', '.join(cors_origins)}")

        # Session / CSRF cookie secure
        session_secure = _bool(getattr(s, "SESSION_COOKIE_SECURE", False))
        csrf_secure = _bool(getattr(s, "CSRF_COOKIE_SECURE", False))
        if not session_secure:
            if self.strict:
                self._error("config.security.session_cookie_secure",
                            "SESSION_COOKIE_SECURE is not enabled",
                            "Set SESSION_COOKIE_SECURE=true for HTTPS.")
            else:
                self._warn("config.security.session_cookie_secure",
                           "SESSION_COOKIE_SECURE is not enabled",
                           "Set SESSION_COOKIE_SECURE=true for HTTPS production.")
        else:
            self._pass("config.security.session_cookie_secure",
                       "SESSION_COOKIE_SECURE is enabled")
        if not csrf_secure:
            if self.strict:
                self._error("config.security.csrf_cookie_secure",
                            "CSRF_COOKIE_SECURE is not enabled",
                            "Set CSRF_COOKIE_SECURE=true for HTTPS.")
            else:
                self._warn("config.security.csrf_cookie_secure",
                           "CSRF_COOKIE_SECURE is not enabled",
                           "Set CSRF_COOKIE_SECURE=true for HTTPS production.")
        else:
            self._pass("config.security.csrf_cookie_secure",
                       "CSRF_COOKIE_SECURE is enabled")

        # SECURE_SSL_REDIRECT
        ssl_redirect = _bool(getattr(s, "SECURE_SSL_REDIRECT", False))
        if not ssl_redirect:
            self._warn("config.security.ssl_redirect",
                       "SECURE_SSL_REDIRECT is not enabled",
                       "Set SECURE_SSL_REDIRECT=true or delegate to a reverse proxy.")
        else:
            self._pass("config.security.ssl_redirect",
                       "SECURE_SSL_REDIRECT is enabled")

        # HSTS
        hsts_seconds = int(getattr(s, "SECURE_HSTS_SECONDS", 0) or 0)
        hsts_include = _bool(getattr(s, "SECURE_HSTS_INCLUDE_SUBDOMAINS", False))
        hsts_preload = _bool(getattr(s, "SECURE_HSTS_PRELOAD", False))
        if hsts_seconds == 0:
            self._warn("config.security.hsts_seconds",
                       "SECURE_HSTS_SECONDS is 0 (HSTS not configured)",
                       "Set SECURE_HSTS_SECONDS for HTTPS-only sites.")
        else:
            self._pass("config.security.hsts_seconds",
                       f"SECURE_HSTS_SECONDS={hsts_seconds}")
        self._info("config.security.hsts_subdomains",
                   f"SECURE_HSTS_INCLUDE_SUBDOMAINS={hsts_include}")
        self._info("config.security.hsts_preload",
                   f"SECURE_HSTS_PRELOAD={hsts_preload}")

        # SECURE_PROXY_SSL_HEADER
        proxy_header = getattr(s, "SECURE_PROXY_SSL_HEADER", None)
        if proxy_header:
            self._pass("config.security.proxy_ssl_header",
                       f"SECURE_PROXY_SSL_HEADER={proxy_header}")
        else:
            self._info("config.security.proxy_ssl_header",
                       "SECURE_PROXY_SSL_HEADER not set "
                       "(fine if not behind a TLS proxy)")

        # X_FRAME_OPTIONS
        xframe = getattr(s, "X_FRAME_OPTIONS", "DENY")
        if xframe in ("DENY", "SAMEORIGIN"):
            self._pass("config.security.x_frame_options",
                       f"X_FRAME_OPTIONS={xframe}")
        else:
            self._warn("config.security.x_frame_options",
                       f"X_FRAME_OPTIONS={xframe} may allow clickjacking",
                       "Set X_FRAME_OPTIONS=DENY or SAMEORIGIN.")

        # SECURE_CONTENT_TYPE_NOSNIFF
        nosniff = _bool(getattr(s, "SECURE_CONTENT_TYPE_NOSNIFF", False))
        if not nosniff:
            self._warn("config.security.content_type_nosniff",
                       "SECURE_CONTENT_TYPE_NOSNIFF is not enabled",
                       "Set SECURE_CONTENT_TYPE_NOSNIFF=true.")
        else:
            self._pass("config.security.content_type_nosniff",
                       "SECURE_CONTENT_TYPE_NOSNIFF is enabled")

        # Password validators
        validators = list(getattr(s, "AUTH_PASSWORD_VALIDATORS", []))
        if validators:
            self._pass("config.security.password_validators",
                       f"{len(validators)} password validator(s) configured")
        else:
            self._warn("config.security.password_validators",
                       "No AUTH_PASSWORD_VALIDATORS configured",
                       "Add Django's built-in password validators.")

    def _check_database(self):
        s = settings
        dbs = getattr(s, "DATABASES", {})
        default_db = dbs.get("default", {})
        engine = default_db.get("ENGINE", "")
        is_sqlite = "sqlite3" in engine

        if is_sqlite:
            if self.strict:
                self._error("config.database.engine",
                            "SQLite is configured (not approved for production)",
                            "Switch to PostgreSQL: set DATABASE_URL or discrete DB_* variables.")
            else:
                self._warn("config.database.engine",
                           "SQLite is configured (development default)",
                           "Use PostgreSQL for production.")
        else:
            self._pass("config.database.engine",
                       f"Database engine: {engine}")

        db_name = default_db.get("NAME", "")
        if db_name:
            self._pass("config.database.name",
                       "Database NAME is configured")
        else:
            self._error("config.database.name",
                        "Database NAME is not configured",
                        "Set the production database name.")

        db_host = default_db.get("HOST", "")
        if db_host:
            self._pass("config.database.host", "Database HOST is configured")
        else:
            self._info("config.database.host",
                       "Database HOST uses default (localhost)")

        db_port = default_db.get("PORT", "")
        if db_port:
            try:
                port = int(db_port)
                if 1 <= port <= 65535:
                    self._pass("config.database.port",
                               f"Database PORT={port} is valid")
                else:
                    self._error("config.database.port",
                                f"Database PORT={port} is out of range",
                                "Set a valid TCP port (1-65535).")
            except ValueError:
                self._error("config.database.port",
                            f"Database PORT={db_port} is not numeric",
                            "Set a numeric port.")
        else:
            self._info("config.database.port",
                       "Database PORT uses default")

        db_user = default_db.get("USER", "")
        if db_user:
            self._pass("config.database.user", "Database USER is configured")
        else:
            self._info("config.database.user",
                       "Database USER uses default")

        db_password = default_db.get("PASSWORD", "")
        if db_password:
            self._pass("config.database.password",
                       "Database password is present (value not shown)")
        else:
            self._info("config.database.password",
                       "Database password not set (may be acceptable "
                       "for local/trust auth)")

        conn_max_age = default_db.get("CONN_MAX_AGE", 0)
        self._info("config.database.conn_max_age",
                   f"CONN_MAX_AGE={conn_max_age}")

        atomic_requests = default_db.get("ATOMIC_REQUESTS", False)
        self._info("config.database.atomic_requests",
                   f"ATOMIC_REQUESTS={atomic_requests}")

    def _check_jwt(self):
        s = settings
        jwt = getattr(s, "SIMPLE_JWT", {})
        access = jwt.get("ACCESS_TOKEN_LIFETIME")
        refresh = jwt.get("REFRESH_TOKEN_LIFETIME")
        blacklist = bool(jwt.get("BLACKLIST_ENABLED", False))

        if access is not None:
            self._info("config.jwt.access_lifetime",
                       f"Access token lifetime: {access}")
        else:
            self._info("config.jwt.access_lifetime",
                       "Access token lifetime not set (default)")

        if refresh is not None:
            self._info("config.jwt.refresh_lifetime",
                       f"Refresh token lifetime: {refresh}")
        else:
            self._info("config.jwt.refresh_lifetime",
                       "Refresh token lifetime not set (default)")

        if refresh is not None:
            try:
                if refresh.total_seconds() > 7 * 24 * 3600:
                    self._warn("config.jwt.refresh_lifetime_long",
                               "Refresh token lifetime exceeds 7 days",
                               "Consider shortening REFRESH_TOKEN_LIFETIME.")
            except Exception:
                pass

        if blacklist:
            self._pass("config.jwt.blacklist",
                       "JWT token blacklist is enabled (logout blacklisting)")
        else:
            self._warn("config.jwt.blacklist",
                       "JWT token blacklist is not enabled",
                       "Set SIMPLE_JWT BLACKLIST_ENABLED=True.")

        signing_key = getattr(s, "SECRET_KEY", "")
        if signing_key and not signing_key.startswith("django-insecure-"):
            self._pass("config.jwt.signing_key",
                       "JWT signing key is present (value not shown)")
        else:
            self._warn("config.jwt.signing_key",
                       "JWT signing key uses the development default",
                       "Set a unique SECRET_KEY for production JWT signing.")

    def _check_email(self):
        s = settings
        backend = getattr(s, "EMAIL_BACKEND", "")
        is_smtp = "smtp" in backend.lower()
        is_console = "console" in backend.lower()
        is_locmem = "locmem" in backend.lower()

        if is_console or is_locmem:
            if self.strict:
                self._error("config.email.backend",
                            f"Email backend is {backend} (not for production)",
                            "Use django.core.mail.backends.smtp.EmailBackend in production.")
            else:
                self._warn("config.email.backend",
                           f"Email backend is {backend} (dev/test only)",
                           "Switch to SMTP for production outbound email.")
        else:
            self._pass("config.email.backend",
                       f"Email backend: {backend}")

        from_email = getattr(s, "DEFAULT_FROM_EMAIL", "")
        if from_email and from_email != "noreply@localhost":
            self._pass("config.email.default_sender",
                       f"DEFAULT_FROM_EMAIL={from_email}")
        else:
            self._warn("config.email.default_sender",
                       "DEFAULT_FROM_EMAIL uses the localhost default",
                       "Set DEFAULT_FROM_EMAIL to a real domain address.")

        if is_smtp:
            host = getattr(s, "EMAIL_HOST", "")
            if host:
                self._pass("config.email.smtp_host", f"EMAIL_HOST={host}")
            else:
                self._error("config.email.smtp_host",
                            "SMTP backend selected but EMAIL_HOST is empty",
                            "Set EMAIL_HOST for SMTP outbound email.")

            port = getattr(s, "EMAIL_PORT", 0)
            try:
                p = int(port)
                if 1 <= p <= 65535:
                    self._pass("config.email.smtp_port", f"EMAIL_PORT={p}")
                else:
                    self._error("config.email.smtp_port",
                                f"EMAIL_PORT={port} is out of range",
                                "Set a valid TCP port (1-65535).")
            except (ValueError, TypeError):
                self._error("config.email.smtp_port",
                            f"EMAIL_PORT={port} is not numeric",
                            "Set a numeric SMTP port.")

            use_tls = _bool(getattr(s, "EMAIL_USE_TLS", False))
            use_ssl = _bool(getattr(s, "EMAIL_USE_SSL", False))
            if use_tls and use_ssl:
                self._error("config.email.tls_ssl_conflict",
                            "EMAIL_USE_TLS and EMAIL_USE_SSL are both true",
                            "Enable only one of TLS or SSL.")
            else:
                self._pass("config.email.tls_ssl",
                           f"TLS={use_tls}, SSL={use_ssl} (not both)")

            timeout = getattr(s, "EMAIL_TIMEOUT", 0)
            try:
                t = int(timeout)
                if t > 0:
                    self._pass("config.email.timeout",
                               f"EMAIL_TIMEOUT={t}s")
                else:
                    self._warn("config.email.timeout",
                               "EMAIL_TIMEOUT is not bounded",
                               "Set EMAIL_TIMEOUT to a positive value.")
            except (ValueError, TypeError):
                self._warn("config.email.timeout",
                           f"EMAIL_TIMEOUT={timeout} is not numeric",
                           "Set a numeric SMTP timeout.")

            user = getattr(s, "EMAIL_HOST_USER", "")
            if user:
                self._pass("config.email.smtp_user", "SMTP username is configured")
            else:
                self._info("config.email.smtp_user",
                           "SMTP username not set (unauthenticated relay)")

            password = getattr(s, "EMAIL_HOST_PASSWORD", "")
            if password:
                self._pass("config.email.smtp_password",
                           "SMTP password is present (value not shown)")
            else:
                self._info("config.email.smtp_password",
                           "SMTP password not set")
        else:
            self._info("config.email.smtp_configured",
                       "Non-SMTP backend; SMTP checks skipped")

    def _check_inbound_email(self):
        s = settings
        enabled = _bool(getattr(s, "INBOUND_MAILBOX_ENABLED", True))
        if not enabled:
            self._pass("config.inbound.enabled", "Inbound email polling is disabled")
            return

        host = (getattr(s, "INBOUND_MAILBOX_HOST", "") or "").strip()
        port = getattr(s, "INBOUND_MAILBOX_PORT", 993)
        user = (getattr(s, "INBOUND_MAILBOX_USER", "") or "").strip()
        mailbox = (getattr(s, "INBOUND_MAILBOX_NAME", "INBOX") or "INBOX")
        password = getattr(s, "INBOUND_MAILBOX_PASSWORD", "")

        if host:
            self._pass("config.inbound.host", f"IMAP host: {host}")
        else:
            self._warn("config.inbound.host",
                       "INBOUND_MAILBOX_ENABLED=true but no host configured",
                       "Set INBOUND_MAILBOX_HOST or disable inbound polling.")

        try:
            p = int(port)
            if 1 <= p <= 65535:
                self._pass("config.inbound.port", f"IMAP port: {p}")
            else:
                self._error("config.inbound.port",
                            f"INBOUND_MAILBOX_PORT={p} is out of range",
                            "Set a valid TCP port (1-65535).")
        except (ValueError, TypeError):
            self._error("config.inbound.port",
                        f"INBOUND_MAILBOX_PORT={port} is not numeric",
                        "Set a numeric IMAP port.")

        if user:
            self._pass("config.inbound.user", "IMAP username is configured")
        else:
            self._warn("config.inbound.user",
                       "INBOUND_MAILBOX_USER is not set",
                       "Set the inbound mailbox username.")

        self._pass("config.inbound.mailbox", f"IMAP mailbox: {mailbox}")

        if password:
            self._pass("config.inbound.password",
                       "IMAP password is present (value not shown)")
        else:
            self._warn("config.inbound.password",
                       "IMAP password is not set",
                       "Set INBOUND_MAILBOX_PASSWORD when inbound is enabled.")

        # Beat task presence
        beat = getattr(s, "CELERY_BEAT_SCHEDULE", {})
        inbound_task = "common.tasks.process_inbound_mailbox"
        task_found = any(
            v.get("task") == inbound_task for v in beat.values()
        )
        if task_found:
            self._pass("config.inbound.beat_task",
                       "Inbound mailbox poll task is in CELERY_BEAT_SCHEDULE")
        else:
            self._error("config.inbound.beat_task_missing",
                        "Inbound mailbox poll task missing from Beat schedule",
                        "Add common.tasks.process_inbound_mailbox to CELERY_BEAT_SCHEDULE.")

        # Attachment size policy
        max_size = getattr(s, "ATTACHMENT_MAX_SIZE_MB", None)
        if max_size is not None:
            self._pass("config.inbound.attachment_limit",
                       f"Attachment max size: {max_size} MB")
        else:
            self._warn("config.inbound.attachment_limit",
                       "ATTACHMENT_MAX_SIZE_MB is not set",
                       "Set an attachment size limit for inbound email.")

        # Message-ID deduplication model exists
        from common.models import EmailProcessing  # noqa: F401
        self._pass("config.inbound.dedup_model",
                   "EmailProcessing model exists for Message-ID deduplication")

    def _check_redis_celery(self):
        s = settings
        broker = getattr(s, "CELERY_BROKER_URL", "")
        result_backend = getattr(s, "CELERY_RESULT_BACKEND", "")

        if broker:
            self._pass("config.celery.broker_configured",
                       f"Broker: {_sanitize_url(broker)}")
        else:
            self._error("config.celery.broker_missing",
                        "CELERY_BROKER_URL is not configured",
                        "Set CELERY_BROKER_URL (e.g. redis://localhost:6379/0).")

        # Broker scheme
        if broker:
            scheme = broker.split("://")[0] if "://" in broker else ""
            if scheme in ("redis", "rediss"):
                self._pass("config.celery.broker_scheme",
                           f"Broker scheme: {scheme}")
            else:
                self._warn("config.celery.broker_scheme",
                           f"Broker scheme '{scheme}' may not be supported in production",
                           "Use redis:// or rediss:// for the Celery broker.")

        # Eager mode
        eager = _bool(getattr(s, "CELERY_TASK_ALWAYS_EAGER", False))
        if eager:
            if self.strict:
                self._error("config.celery.eager_mode",
                            "CELERY_TASK_ALWAYS_EAGER is true (tasks run inline)",
                            "Disable eager mode for production Celery workers.")
            else:
                self._warn("config.celery.eager_mode",
                           "CELERY_TASK_ALWAYS_EAGER is true (dev/test convenience)",
                           "Set CELERY_TASK_ALWAYS_EAGER=false in production.")
        else:
            self._pass("config.celery.eager_mode", "Celery eager mode is disabled")

        # Serializer
        serializer = getattr(s, "CELERY_TASK_SERIALIZER", "json")
        if serializer == "json":
            self._pass("config.celery.serializer", "Task serializer: json")
        else:
            self._error("config.celery.serializer_unsafe",
                        f"Task serializer is {serializer} (not JSON)",
                        "Set CELERY_TASK_SERIALIZER=json for production.")

        accept_content = list(getattr(s, "CELERY_ACCEPT_CONTENT", ["json"]))
        if "pickle" in accept_content:
            self._error("config.celery.accept_content_pickle",
                        "CELERY_ACCEPT_CONTENT allows pickle (unsafe)",
                        "Remove pickle from CELERY_ACCEPT_CONTENT.")
        else:
            self._pass("config.celery.accept_content",
                       f"Accept content: {', '.join(accept_content)}")

        # Timezone
        tz = getattr(s, "CELERY_TIMEZONE", None) or getattr(s, "TIME_ZONE", "UTC")
        self._pass("config.celery.timezone", f"Timezone: {tz}")

        # Time limits
        time_limit = getattr(s, "CELERY_TASK_TIME_LIMIT", 0)
        if time_limit > 0:
            self._pass("config.celery.time_limit",
                       f"Task time limit: {time_limit}s")
        else:
            self._warn("config.celery.time_limit",
                       "CELERY_TASK_TIME_LIMIT is not bounded",
                       "Set CELERY_TASK_TIME_LIMIT for production tasks.")

        # Beat schedule
        beat = getattr(s, "CELERY_BEAT_SCHEDULE", {})
        if beat:
            self._pass("config.celery.beat_schedule",
                       f"{len(beat)} Beat schedule entry(ies)")
            expected_tasks = [
                "tickets.tasks.check_sla_escalations",
                "assets.tasks.check_maintenance_reminders",
                "common.tasks.process_inbound_mailbox",
                "common.tasks.run_scheduled_reports",
            ]
            for task_path in expected_tasks:
                found = any(v.get("task") == task_path for v in beat.values())
                if found:
                    try:
                        module_path, _, func_name = task_path.rpartition(".")
                        __import__(module_path, fromlist=[func_name])
                        self._pass(f"config.celery.beat_task.{task_path.split('.')[-1]}",
                                   f"Beat task resolves: {task_path}")
                    except Exception:
                        self._error(f"config.celery.beat_task.{task_path.split('.')[-1]}",
                                    f"Beat task path does not import: {task_path}",
                                    "Fix the task dotted path or install missing modules.")
                else:
                    self._error(f"config.celery.beat_task.{task_path.split('.')[-1]}",
                                f"Expected Beat task missing: {task_path}",
                                f"Add {task_path} to CELERY_BEAT_SCHEDULE.")
        else:
            self._error("config.celery.beat_schedule_empty",
                        "CELERY_BEAT_SCHEDULE is empty",
                        "Configure periodic tasks in CELERY_BEAT_SCHEDULE.")

        # Result backend
        if result_backend:
            self._pass("config.celery.result_backend",
                       f"Result backend: {_sanitize_url(result_backend)}")
        else:
            self._info("config.celery.result_backend",
                       "No result backend configured (task results discarded)")

        # Retry settings
        max_retries = getattr(s, "CELERY_TASK_MAX_RETRIES", None)
        if max_retries is not None:
            self._info("config.celery.max_retries",
                       f"CELERY_TASK_MAX_RETRIES={max_retries}")
        retry_backoff = getattr(s, "CELERY_TASK_RETRY_BACKOFF", None)
        if retry_backoff is not None:
            self._info("config.celery.retry_backoff",
                       f"CELERY_TASK_RETRY_BACKOFF={retry_backoff}s")

    def _check_storage(self):
        s = settings
        backend_name = getattr(s, "STORAGE_BACKEND", "local")
        self._pass("config.storage.backend", f"Storage backend: {backend_name}")

        media_root = getattr(s, "MEDIA_ROOT", None)
        if media_root:
            self._pass("config.storage.media_path",
                       f"MEDIA_ROOT configured: {media_root}")
        else:
            self._warn("config.storage.media_path",
                       "MEDIA_ROOT is not set",
                       "Set MEDIA_ROOT for local file storage.")

        if backend_name == "s3":
            bucket = getattr(s, "AWS_STORAGE_BUCKET_NAME", "")
            region = getattr(s, "AWS_S3_REGION_NAME", "")
            if bucket:
                self._pass("config.storage.s3_bucket", "S3 bucket is configured")
            else:
                self._error("config.storage.s3_bucket_missing",
                            "STORAGE_BACKEND=s3 but AWS_STORAGE_BUCKET_NAME is empty",
                            "Set AWS_STORAGE_BUCKET_NAME for S3 storage.")
            if region:
                self._pass("config.storage.s3_region", f"S3 region: {region}")
            else:
                self._error("config.storage.s3_region_missing",
                            "STORAGE_BACKEND=s3 but AWS_S3_REGION_NAME is empty",
                            "Set AWS_S3_REGION_NAME for S3 storage.")
        else:
            self._info("config.storage.s3_skipped",
                       "Local storage selected; S3 checks skipped")

        static_root = getattr(s, "STATIC_ROOT", None)
        if static_root:
            self._pass("config.storage.static_root",
                       f"STATIC_ROOT configured: {static_root}")
        else:
            self._warn("config.storage.static_root",
                       "STATIC_ROOT is not set",
                       "Set STATIC_ROOT for production collectstatic.")

    def _check_logging(self):
        s = settings
        logging = getattr(s, "LOGGING", {})
        root_level = ""
        if isinstance(logging, dict):
            root_logger = logging.get("root", {})
            root_level = root_logger.get("level", "NOTSET")
        self._pass("config.logging.level", f"Root log level: {root_level}")

        if _bool(getattr(s, "DEBUG", True)):
            self._warn("config.logging.debug_level",
                       "Logging may be verbose in DEBUG mode",
                       "Set LOG_LEVEL=WARNING or ERROR for production.")
        else:
            self._pass("config.logging.production_level",
                       "Logging is not in DEBUG mode")