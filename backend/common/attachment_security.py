"""Shared attachment download security helpers.

Provides safe filename handling for Content-Disposition headers so that
original filenames can never inject CRLF sequences, path traversal, or
HTML into download responses. Used by ticket and asset attachment download
endpoints.
"""

import os
import re

# Characters never allowed inside a quoted filename parameter value.
_CRLF_RE = re.compile(r"[\r\n]+")
# Control characters and path separators that must not reach the header.
_UNSAFE_RE = re.compile(r"[\\/:*?\"<>|\x00-\x1f\x7f]")


def safe_content_disposition_filename(name):
    """Return a safe, displayable filename for Content-Disposition.

    Strips directory components, CRLF sequences, and unsafe control/path
    characters. Falls back to "download" when nothing usable remains.
    """
    if not name:
        return "download"
    # Keep only the final path component (defence in depth against upload_to
    # bugs that might store a relative path).
    base = os.path.basename(str(name))
    # Remove CRLF (header injection).
    base = _CRLF_RE.sub("", base)
    # Remove unsafe characters.
    base = _UNSAFE_RE.sub("_", base)
    base = base.strip(" .")
    if not base:
        base = "download"
    return base


def add_download_security_headers(response):
    """Add standard safe-download headers to a FileResponse."""
    response["X-Content-Type-Options"] = "nosniff"
    return response
