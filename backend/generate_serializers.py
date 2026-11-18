"""Generate monitoring serializers.py."""
import os

path = "backend/monitoring/serializers.py"


def generate_serializers(output_path=path):
    """Generate the monitoring serializers.py file at output_path."""
    if os.path.exists(output_path):
        os.remove(output_path)
    with open(output_path, "w") as f:
        f.write('"""Rest Framework serializers for monitoring module."""\n')
    print("Part 1: serializers.py created")


if __name__ == "__main__":
    generate_serializers(path)
