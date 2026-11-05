"""SQLite backup verification: integrity check on a temporary copy.

Creates a temporary file-based SQLite database, copies it to a temp path,
runs PRAGMA integrity_check against the copy, and deletes only the
temporary artifact. Never touches the live development database.
"""

import os
import shutil
import sqlite3
import tempfile

from django.test import TestCase


class SqliteBackupVerificationTests(TestCase):
    """Safe backup verification that never mutates the live database."""

    def _make_temp_db(self):
        """Create a temp file-based SQLite DB with a table + row."""
        tmp_dir = tempfile.mkdtemp(prefix="backup_verify_")
        db_path = os.path.join(tmp_dir, "source.sqlite3")
        con = sqlite3.connect(db_path)
        try:
            con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
            con.execute("INSERT INTO t (name) VALUES ('x')")
            con.commit()
        finally:
            con.close()
        return tmp_dir, db_path

    def test_integrity_check_on_temp_copy(self):
        """Copy a temp DB, integrity_check the copy, delete only temp."""
        tmp_dir, src = self._make_temp_db()
        try:
            copy_dir = tempfile.mkdtemp(prefix="backup_copy_")
            tmp_db = os.path.join(copy_dir, "verify.sqlite3")
            try:
                shutil.copy2(src, tmp_db)
                self.assertTrue(os.path.exists(tmp_db))
                con = sqlite3.connect(tmp_db)
                try:
                    row = con.execute("PRAGMA integrity_check").fetchone()
                finally:
                    con.close()
                self.assertEqual(row[0], "ok", f"integrity_check: {row[0]}")
            finally:
                shutil.rmtree(copy_dir, ignore_errors=True)
            self.assertFalse(os.path.exists(tmp_db), "temp copy must be removed")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_backup_never_modifies_source(self):
        """Verify a read-only copy + integrity_check leaves source unchanged."""
        tmp_dir, src = self._make_temp_db()
        try:
            mtime_before = os.path.getmtime(src)
            copy_dir = tempfile.mkdtemp(prefix="backup_ro_")
            tmp_db = os.path.join(copy_dir, "verify.sqlite3")
            try:
                shutil.copy2(src, tmp_db)
                con = sqlite3.connect(tmp_db)
                try:
                    con.execute("PRAGMA integrity_check").fetchone()
                finally:
                    con.close()
            finally:
                shutil.rmtree(copy_dir, ignore_errors=True)
            mtime_after = os.path.getmtime(src)
            self.assertEqual(mtime_before, mtime_after,
                             "source DB must not be modified by verify")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
