#!/usr/bin/env python3
with open('D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\App.jsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Insert service route checks after line 341 (index 340), which is the closing } of cmdb block
# The new lines should go between index 340 and 341

# New service route checks to insert
new_lines = [
    "  if (route.startsWith('#/services/') && route.match(/\/graph$/)) return <ServiceGraphPage />;\n",
    "  if (route.startsWith('#/services/') && route.match(/\/impact$/)) return <ServiceImpactPage />;\n",
    "  if (route.startsWith('#/services/') && route.match(/\/single-points-of-failure$/)) return <ServiceSPOFPage />;\n",
]

# Insert after line 341 (index 340), which is "  }" closing the cmdb if block
# We want to insert BEFORE the #/problem-management check at line 342 (index 341)
insert_at = 341  # This is the index of the "}" line

# Insert the new lines
for i, new_line in enumerate(new_lines):
    lines.insert(insert_at + i, new_line)

with open('D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\App.jsx', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"Inserted {len(new_lines)} service route checks")
# Print the affected lines to verify
for i in range(338, 350):
    print(f"Line {i+1}: {lines[i].rstrip()}")