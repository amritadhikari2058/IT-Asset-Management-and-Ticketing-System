import csv
import io
import logging

from openpyxl import load_workbook
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)

IMPORT_BATCH_SIZE = 250


def batches(values, size=IMPORT_BATCH_SIZE):
    iterator = iter(values)
    while True:
        batch = []
        try:
            for _ in range(size):
                batch.append(next(iterator))
        except StopIteration:
            pass
        if not batch:
            return
        yield batch


def _validated_headers(raw_headers, allowed):
    headers = [str(value or "").strip() for value in raw_headers]
    if allowed is None:
        return headers
    unknown = [value for value in headers if value and value not in allowed]
    if unknown:
        raise ValidationError({"file": "unknown columns: "
                               + ", ".join(unknown)})
    if not any(value in allowed for value in headers):
        raise ValidationError({"file": "header row missing"})
    return headers


def iter_uploaded_rows(upload, allowed, max_file_bytes, max_rows,
                       xlsx_extensions=(".xlsx", ".xlsm"),
                       skip_empty_xlsx_rows=True,
                       skip_empty_csv_rows=True,
                       reject_extra_csv_values=False,
                       error_message=None,
                       reject_duplicate_headers=False,
                       strip_empty_xlsx_values=False):
    """Yield normalized rows without retaining the uploaded file's contents."""
    filename = (getattr(upload, "name", "") or "").lower()
    size = getattr(upload, "size", None)
    if size is not None and size > max_file_bytes:
        limit_mb = max_file_bytes / (1024 * 1024)
        raise ValidationError({
            "file": f"Uploaded file is too large. Maximum size is "
                    f"{limit_mb:.0f} MB."})

    workbook = None
    text_stream = None
    try:
        upload.seek(0)
        if filename.endswith(xlsx_extensions):
            workbook = load_workbook(upload, read_only=True, data_only=True)
            worksheet = workbook.active
            if worksheet is None:
                raise ValueError("workbook has no worksheets")
            source_rows = worksheet.iter_rows(values_only=True)
            raw_headers = next(source_rows, None)
            if raw_headers is None:
                raise ValueError("spreadsheet is empty; header row missing")
            headers = _validated_headers(raw_headers, allowed)
            if reject_duplicate_headers and any(
                    headers.count(header) > 1 for header in headers if header):
                raise ValidationError({
                    "file": "Duplicate column headers are not allowed."})
            row_count = 0
            for values in source_rows:
                if skip_empty_xlsx_rows and not any(
                        value is not None and
                        (str(value).strip() != "" if strip_empty_xlsx_values
                         else bool(value))
                        for value in values):
                    continue
                row_count += 1
                if row_count > max_rows:
                    raise ValidationError({
                        "file": f"Too many rows in uploaded file. Maximum is "
                                f"{max_rows}."})
                yield dict(zip(headers, values))
            return

        text_stream = io.TextIOWrapper(
            upload, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text_stream, strict=True)
        if reader.fieldnames is None:
            raise ValueError("CSV is empty; header row missing")
        reader.fieldnames = _validated_headers(reader.fieldnames, allowed)
        if reject_duplicate_headers and any(
                reader.fieldnames.count(header) > 1
                for header in reader.fieldnames if header):
            raise ValidationError({
                "file": "Duplicate column headers are not allowed."})
        row_count = 0
        for row in reader:
            if skip_empty_csv_rows and not any(
                    value is not None and str(value).strip() != ""
                    for value in row.values()):
                continue
            row_count += 1
            if row_count > max_rows:
                raise ValidationError({
                    "file": f"Too many rows in uploaded file. Maximum is "
                            f"{max_rows}."})
            normalized = {}
            for key, value in row.items():
                if key is None:
                    if reject_extra_csv_values:
                        raise ValueError("row has more values than the header")
                    continue
                normalized[key.strip()] = value
            yield normalized
    except ValidationError:
        raise
    except Exception as exc:
        logger.exception("Could not parse uploaded import file %r", filename)
        if error_message:
            raise ValidationError({"file": error_message}) from exc
        raise ValidationError({
            "file": "Could not read the uploaded file. Expected a UTF-8 CSV "
                    "or a valid XLSX workbook with a header row."}) from exc
    finally:
        if workbook is not None:
            workbook.close()
        if text_stream is not None:
            try:
                text_stream.detach()
            except ValueError:
                pass
        try:
            upload.seek(0)
        except (AttributeError, OSError, ValueError):
            pass


def count_uploaded_rows(upload, allowed, max_file_bytes, max_rows,
                        **options):
    return sum(1 for _ in iter_uploaded_rows(
        upload, allowed, max_file_bytes, max_rows, **options))
