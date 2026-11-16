"""Generate monitoring models.py."""
import os
path = "backend/monitoring/models.py"
if os.path.exists(path):
    os.remove(path)
with open(path, "w") as f:
    f.write("# Monitoring models generated automatically\n")
print("Generated models.py")