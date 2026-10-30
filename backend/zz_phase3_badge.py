path = "D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\components.jsx"
src = open(path, encoding="utf-8").read()
lines = src.splitlines()

i_tone1 = next(i for i, l in enumerate(lines) if "in_progress: 'purple'" in l)
lines[i_tone1] = lines[i_tone1].replace("in_progress: 'purple',", "in_progress: 'amber',")
i_tone2 = next(i for i, l in enumerate(lines) if l.strip() == "reopened: 'amber', archived: 'gray',")
lines[i_tone2] = lines[i_tone2].replace("reopened: 'amber',", "reopened: 'purple',")

i_doc = next(i for i, l in enumerate(lines) if "Small status/priority indicator" in l)
labels = [
    "const STATUS_LABELS = {",
    "  open: 'Open', in_progress: 'In progress', resolved: 'Resolved', closed: 'Closed',",
    "  reopened: 'Reopened', archived: 'Archived', available: 'Available', assigned: 'Assigned',",
    "  in_repair: 'In repair', retired: 'Retired', lost: 'Lost', active: 'Active', inactive: 'Inactive',",
    "};",
    "const PRIORITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' };",
    "",
    "/** Human-readable label for status/priority values (kind: 'status' | 'priority'). */",
    "function prettyValue(kind, value) {",
    "  const key = String(value ?? '');",
    "  const map = kind === 'priority' ? PRIORITY_LABELS : STATUS_LABELS;",
    "  const hit = map[key];",
    "  if (hit) return hit;",
    "  return key.replace(/_/g, ' ').replace(/\\b\\w/g, (c) => c.toUpperCase());",
    "}",
    "",
]
lines[i_doc:i_doc] = labels
i_text = next(i for i, l in enumerate(lines) if l.strip().startswith("const text = label"))
lines[i_text] = "  const text = label ?? prettyValue(kind, value);"

open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("badge ok")
