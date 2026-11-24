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


def _mark_job(job, status, error="", size="", duration="", artifact_path=""):
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
    if artifact_path:
        job.artifact_path = artifact_path
        update_fields.append("artifact_path")
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
                      duration=result.get("duration", ""),
                      artifact_path=result.get("artifact_path", ""))
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
            dst = _write_tarball([src], "database")
            size = os.path.getsize(dst)
            return {"status": "success", "size": _human_size(size),
                    "duration": _duration_str(started), "target": target,
                    "artifact_path": dst}
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
                    "duration": _duration_str(started), "target": target,
                    "artifact_path": dst}
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
    project_root = base.parent
    include_env = getattr(settings, "BACKUP_INCLUDE_ENV_FILE", False)
    candidates = [
        project_root / ".env.example",
        project_root / "docker-compose.yml",
        base / "manage.py",
        base / "requirements.txt",
        base / "Dockerfile",
        base / "config" / "settings.py",
        base / "config" / "urls.py",
    ]
    if include_env:
        candidates.insert(0, project_root / ".env")
    for candidate in candidates:
        if candidate.exists():
            files_to_backup.append(str(candidate))

    if not files_to_backup:
        return {"status": "failed", "error": "No config files found to back up."}

    dst = _write_tarball(files_to_backup, "config")
    size = os.path.getsize(dst)
    return {"status": "success", "size": _human_size(size),
            "duration": _duration_str(started), "target": ", ".join(files_to_backup)[:100],
            "artifact_path": dst}


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
            "duration": _duration_str(started), "target": ", ".join(roots)[:100],
            "artifact_path": dst}


def _backup_media(job):
    """Back up the media/attachments directory specifically."""
    started = timezone.now()
    media_root = getattr(settings, "MEDIA_ROOT", None)
    if not media_root or not os.path.exists(media_root):
        return {"status": "failed", "error": "MEDIA_ROOT not found."}

    dst = _write_tarball([str(media_root)], "media")
    size = os.path.getsize(dst)
    return {"status": "success", "size": _human_size(size),
            "duration": _duration_str(started), "target": str(media_root)[:100],
            "artifact_path": dst}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backup_artifact_dir():
    base = getattr(settings, "BACKUP_ARTIFACT_DIR", None) or (
        settings.BASE_DIR / "backup_artifacts")
    os.makedirs(base, exist_ok=True)
    return str(base)


def _write_bytes(data, label):
    """Write bytes to a managed backup artifact file and return the path."""
    ts = timezone.now().strftime("%Y%m%d%H%M%S")
    path = os.path.join(_backup_artifact_dir(), f"backup_{label}_{ts}.dat")
    with open(path, "wb") as f:
        f.write(data)
    return path


def _write_tarball(sources, label):
    """Create a gzipped tarball from files/dirs. Returns the tar path."""
    ts = timezone.now().strftime("%Y%m%d%H%M%S")
    path = os.path.join(_backup_artifact_dir(), f"backup_{label}_{ts}.tar.gz")
    with tarfile.open(path, "w:gz") as tar:
        for src in sources:
            if os.path.isdir(src):
                tar.add(src, arcname=os.path.basename(str(src).rstrip("/\\")))
            elif os.path.isfile(src):
                tar.add(src, arcname=os.path.basename(str(src)))
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


@shared_task(bind=True)
def cleanup_backup_artifacts(self):
    """Expire old restore points and delete orphaned/expired backup artifacts."""
    now = timezone.now()
    expired = RestorePoint.objects.filter(
        is_deleted=False,
        expires_at__isnull=False,
        expires_at__lt=now,
        status="available",
    ).update(status="expired", updated_at=now)

    base = _backup_artifact_dir()
    base_real = os.path.realpath(base)
    referenced = set()
    for path in BackupJob.objects.exclude(artifact_path="").values_list("artifact_path", flat=True):
        try:
            rp = os.path.realpath(path)
            if os.path.commonpath([base_real, rp]) == base_real:
                referenced.add(rp)
        except Exception:
            continue

    deleted_files = 0
    for entry in os.scandir(base_real):
        if not entry.is_file():
            continue
        rp = os.path.realpath(entry.path)
        if rp in referenced:
            continue
        # Only remove files older than the max retention window among schedules, fallback 30 days.
        max_retention = 30
        try:
            from django.db.models import Max
            agg = BackupSchedule.objects.filter(is_deleted=False).aggregate(m=Max("retention_days"))
            if agg.get("m"):
                max_retention = max(max_retention, int(agg["m"]))
        except Exception:
            pass
        age_days = (now.timestamp() - entry.stat().st_mtime) / 86400
        if age_days >= max_retention:
            try:
                os.remove(rp)
                deleted_files += 1
            except OSError:
                logger.warning("Failed to remove backup artifact: %s", rp)

    return {"expired_restore_points": expired, "deleted_files": deleted_files}
