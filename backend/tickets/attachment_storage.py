"""Crash-safe persistence of ticket attachment files.

Django's ``FileField`` writes the physical file during ``Model.save()``,
*before* the database INSERT. If the INSERT (or the history/audit rows
written alongside it) fails, the file stays in storage while no row points
at it -- an orphan that is invisible to the API and only recoverable by
hand.

These helpers invert that order for the ticket attachment API:

1. The upload is written to the model's *configured* storage first and the
   exact stored name is returned.
2. The database record is created afterwards, inside the caller's
   transaction, using that name.
3. If anything in step 2 fails, only the object written in step 1 is
   deleted and the original exception is re-raised.

Only the name returned by this upload's ``storage.save()`` is ever
deleted, so a file belonging to another attachment (or to an earlier
successful upload) can never be removed. Everything goes through the
``FileField``'s storage backend, so local disk and S3-compatible backends
behave the same and no filesystem path is assumed.
"""
import logging

logger = logging.getLogger(__name__)


def _file_field(model):
    return model._meta.get_field("file")


def store_upload(model, upload):
    """Write ``upload`` to the model's storage and return its stored name.

    ``None`` is returned when there is no upload. The ``FileField``'s own
    ``upload_to`` callable is used, so the existing UUID storage layout is
    preserved rather than re-implemented here.
    """
    if upload is None:
        return None
    field = _file_field(model)
    name = field.generate_filename(None, getattr(upload, "name", "") or "")
    return field.storage.save(name, upload)


def delete_stored_file(model, name):
    """Best-effort removal of a file this request just wrote.

    Never raises: cleanup must not mask the exception that triggered it.
    Safe to call repeatedly -- both ``FileSystemStorage.delete`` and
    ``S3Storage.delete`` treat an already-absent object as a no-op.
    """
    if not name:
        return False
    try:
        _file_field(model).storage.delete(name)
        return True
    except Exception:  # pragma: no cover - backend-specific failures
        logger.exception("Could not remove orphaned attachment file %r", name)
        return False
