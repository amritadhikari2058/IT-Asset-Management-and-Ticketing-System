"""Celery Background Tasks for Backup & DR.

Implements real backup job execution: config, database, files, and media backups.
Each task creates a BackupJob row, runs the backup, records the outcome, and
optionally creates a RestorePoint on success.
"""
import logging
import os
import subprocess
import tarfile
import tempfile
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from .models import BackupJob, BackupSchedule, RestorePoint

logger = logging.getLogger(__name__)


def _mark_job(job, status, error="", size="", duration=""):
    """Atomically update a BackupJob's terminal fields."""
    now = timezone.now()
    update_fields = ["status", "finished", "updated_at"]
    job.status = status
    job.finished = now
    if error:
        job.error = error
        update_fields.append("error")
    if size:
        job.size = size
        update_fields.append("size")
    if duration:
        job.duration = duration
        update_fields.append("duration")
    job.save(update_fields=update_fields)
    # Update the schedule's last_run / last_status.
    if job.schedule_id:
        BackupSchedule.objects.filter(pk=job.schedule_id).update(
            last_run=now,
            last_status=status,
        )
    return job


def _create_restore_point(job):
    """Create a RestorePoint from a successful BackupJob."""
    if not job.schedule_id:
        return None
    schedule = BackupSchedule.objects.filter(pk=job.schedule_id).first()
    expires_at = None
    if schedule and schedule.retention_days:
        expires_at = timezone.now() + timedelta(days=schedule.retention_days)
    rp = RestorePoint.objects.create(
        job=job,
        schedule=job.schedule,
        restore_type=job.job_type,
        status="available",
        expires_at=expires_at,
        size=job.size,
        target=job.target,
        created_by=job.created_by,
    )
    return rp


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_backup_job(self, job_pk):
    """Run a single backup job: config / database / files / media.

    Dispatches to the appropriate private handler based on the job's type.
    """
    job = BackupJob.objects.filter(pk=job_pk).first()
    if job is None:
        logger.error("run_backup_job: job %s not found", job_pk)
        return {"status": "not_found", "job": job_pk}

    if job.status != "pending":
        logger.warning("run_backup_job: job %s already %s", job_pk, job.status)
        return {"status": "already_" + job.status, "job": job_pk}

    job.status = "running"
    job.started = timezone.now()
    job.save(update_fields=["status", "started", "updated_at"])

    try:
        if job.job_type == "database":
            result = _backup_database(job)
        elif job.job_type == "config":
            result = _backup_config(job)
        elif job.job_type == "files":
            result = _backup_files(job)
        elif job.job_type == "media":
            result = _backup_media(job)
        else:
            result = {"status": "failed", "error": f"Unknown job type: {job.job_type}"}

        if result.get("status") == "success":
            _mark_job(job, "success", size=result.get("size", ""),
                      duration=result.get("duration", ""))
            _create_restore_point(job)
            logger.info("Backup job %s succeeded: %s", job_pk, result)
            return {"status": "success", "job": job_pk, **result}
        else:
            _mark_job(job, "failed", error=result.get("error", "unknown error"))
            logger.error("Backup job %s failed: %s", job_pk, result.get("error"))
            return {"status": "failed", "job": job_pk, **result}
    except Exception as exc:  # noqa: BLE001 - never let the worker crash
        logger.exception("Backup job %s crashed", job_pk)
        _mark_job(job, "failed", error=str(exc)[:500])
        return {"status": "failed", "job": job_pk, "error": str(exc)[:500]}


def _backup_database(job):
    """Back up the database using the configured Django DB connection."""
    from django.db import connection
    started = timezone.now()
    vendor = connection.vendor
    db_name = connection.settings_dict.get("NAME", "unknown")
    target = f"{vendor}:{db_name}"
    job.target = target
    job.save(update_fields=["target", "updated_at"])

    try:
        if vendor == "sqlite":
            # Copy the SQLite file.
            src = db_name
            if not src or not os.path.exists(src):
                return {"status": "failed", "error": f"SQLite DB file not found: {src}"}
            dst = _write_tarball(src, "database")
            size = os.path.getsize(dst)
            return {"status": "success", "size": _human_size(size),
                    "duration": _duration_str(started), "target": target}
        elif vendor == "postgresql":
            # Use pg_dump if available.
            dump_cmd = [
                "pg_dump",
                "--dbname", f"dbname={db_name}",
                "--format=custom",
                "--file", "-",
            ]
            env = os.environ.copy()
            for key in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT"):
                val = os.environ.get(key)
                if val:
                    env[key] = val
            result = subprocess.run(
                dump_cmd, capture_output=True, env=env, timeout=600,
            )
            if result.returncode != 0:
                return {"status": "failed",
                        "error": result.stderr.decode("utf-8", "ignore")[:500]}
            dst = _write_bytes(result.stdout, "database")
            size = len(result.stdout)
            return {"status": "success", "size": _human_size(size),
                    "duration": _duration_str(started), "target": target}
        else:
            return {"status": "failed", "error": f"Unsupported DB vendor: {vendor}"}
    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "Database backup timed out."}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": str(exc)[:500]}


def _backup_config(job):
    """Back up key configuration files (settings, env, requirements)."""
    started = timezone.now()
    files_to_backup = []
    base = settings.BASE_DIR
    for candidate in [
        base / ".env",
        base / ".env.example",
        base / "manage.py",
        base / "requirements.txt",
        base / "backend" / "config" / "settings.py",
        base / "backend" / "config" / "urls.py",
        base / "docker-compose.yml",
        base / "backend" / "Dockerfile",
    ]:
        if candidate.exists():
            files_to_backup.append(str(candidate))

    if not files_to_backup:
        return {"status": "failed", "error": "No config files found to back up."}

    dst = _write_tarball(files_to_backup, "config")
    size = os.path.getsize(dst)
    return {"status": "success", "size": _human_size(size),
            "duration": _duration_str(started), "target": ", ".join(files_to_backup)[:100]}


def _backup_files(job):
    """Back up file-share style directories (e.g. static/uploads roots)."""
    started = timezone.now()
    roots = []
    media_root = getattr(settings, "MEDIA_ROOT", None)
    if media_root and os.path.exists(media_root):
        roots.append(str(media_root))
    static_root = getattr(settings, "STATIC_ROOT", None)
    if static_root and os.path.exists(static_root):
        roots.append(str(static_root))

    if not roots:
        return {"status": "failed", "error": "No file directories found to back up."}

    dst = _write_tarball(roots, "files")
    size = os.path.getsize(dst)
    return {"status": "success", "size": _human_size(size),
            "duration": _duration_str(started), "target": ", ".join(roots)[:100]}


def _backup_media(job):
    """Back up the media/attachments directory specifically."""
    started = timezone.now()
    media_root = getattr(settings, "MEDIA_ROOT", None)
    if not media_root or not os.path.exists(media_root):
        return {"status": "failed", "error": "MEDIA_ROOT not found."}

    dst = _write_tarball(media_root, "media")
    size = os.path.getsize(dst)
    return {"status": "success", "size": _human_size(size),
            "duration": _duration_str(started), "target": str(media_root)[:100]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_bytes(data, label):
    """Write bytes to a temp file and return the path."""
    fd, path = tempfile.mkstemp(prefix=f"backup_{label}_", suffix=".dat")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def _write_tarball(sources, label):
    """Create a gzipped tarball from a list of files/dirs. Returns the tar path."""
    fd, path = tempfile.mkstemp(prefix=f"backup_{label}_", suffix=".tar.gz")
    os.close(fd)
    with tarfile.open(path, "w:gz") as tar:
        for src in sources:
            if os.path.isdir(src):
                tar.add(src, arcname=os.path.basename(src.rstrip("/")))
            elif os.path.isfile(src):
                tar.add(src, arcname=os.path.basename(src))
    return path


def _human_size(size_bytes):
    if size_bytes is None:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _duration_str(started):
    if not started:
        return ""
    delta = timezone.now() - started
    total = int(delta.total_seconds())
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"
