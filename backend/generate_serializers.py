"""Generate monitoring serializers.py."""
import os

path = "backend/monitoring/serializers.py"
if os.path.exists(path):
    os.remove(path)

with open(path, "w") as f:
    f.write(""""""Rest Framework serializers for monitoring module."""\n")
print("Part 1: serializers.py created")