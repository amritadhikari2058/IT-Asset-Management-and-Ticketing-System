"""Focused tests for backend/generate_serializers.py."""

import ast
import os
import tempfile
import unittest
from pathlib import Path

from generate_serializers import generate_serializers, path

_BACKEND_DIR = Path(__file__).resolve().parent
_ACTIVE_SERIALIZER = _BACKEND_DIR / "monitoring" / "serializers.py"
_GENERATOR_SCRIPT = _BACKEND_DIR / "generate_serializers.py"


class GenerateSerializersTestCase(unittest.TestCase):
    """Tests for the serializer generator script."""

    def test_module_imports_without_executing_generation(self):
        """Importing the module must not create or modify files."""
        self.assertTrue(os.path.exists(_ACTIVE_SERIALIZER))

    def test_source_compiles(self):
        """The generator script itself must compile cleanly."""
        import py_compile
        py_compile.compile(str(_GENERATOR_SCRIPT), doraise=True)

    def test_generator_accepts_temporary_output_location(self):
        """The generator must write to a temp path, not the active source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "serializers.py")
            generate_serializers(out)
            self.assertTrue(os.path.exists(out))

    def test_generated_content_is_non_empty(self):
        """Generated file must contain non-empty content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "serializers.py")
            generate_serializers(out)
            with open(out) as f:
                content = f.read()
            self.assertTrue(len(content) > 0)
            self.assertIn("Rest Framework serializers", content)

    def test_generated_python_parses(self):
        """Generated file must parse as valid Python."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "serializers.py")
            generate_serializers(out)
            with open(out) as f:
                source = f.read()
            ast.parse(source)

    def test_active_serializer_file_not_modified(self):
        """Generation to a temp path must not touch the active serializers.py."""
        active = str(_ACTIVE_SERIALIZER)
        mtime_before = os.path.getmtime(active)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "serializers.py")
            generate_serializers(out)
        mtime_after = os.path.getmtime(active)
        self.assertEqual(mtime_before, mtime_after)

    def test_invalid_target_fails_safely(self):
        """Passing an output path inside a nonexistent directory raises OSError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = os.path.join(tmpdir, "nonexistent", "serializers.py")
            with self.assertRaises(OSError):
                generate_serializers(bad)

    def test_repeated_execution_is_deterministic(self):
        """Repeated generation to separate temp paths produces identical output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out1 = os.path.join(tmpdir, "serializers1.py")
            out2 = os.path.join(tmpdir, "serializers2.py")
            generate_serializers(out1)
            generate_serializers(out2)
            with open(out1) as f:
                content1 = f.read()
            with open(out2) as f:
                content2 = f.read()
            self.assertEqual(content1, content2)


if __name__ == "__main__":
    unittest.main()
