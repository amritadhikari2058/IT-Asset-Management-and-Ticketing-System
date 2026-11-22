"""Generate monitoring serializers.py."""

import os
from pathlib import Path

# Resolve path relative to this file's location (backend/),
# so it works regardless of cwd when pytest runs from backend/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
path = str(_PROJECT_ROOT / "monitoring" / "serializers.py")


def generate_serializers(output_path=path):
    """Generate the monitoring serializers.py file at output_path."""
    if os.path.exists(output_path):
        os.remove(output_path)
    with open(output_path, "w") as f:
        f.write('"""Rest Framework serializers for monitoring module."""\n')
    print("Part 1: serializers.py created")


if __name__ == "__main__":
    generate_serializers(path)