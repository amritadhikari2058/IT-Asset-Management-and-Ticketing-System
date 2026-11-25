#!/usr/bin/env python3
with open('D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\App.jsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# The NAV array starts at line 71. I need to add new entries.
# Let me find where to insert the new cmdb report/service routes.

# First, let me see the structure around the cmdb section
# The cmdb entry is at line 101: { hash: '#/cmdb', label: 'CMDB', staffOnly: true }

# I'll add new entries after the existing cmdb-related NAV items.
# Looking at lines 190-268, the TITLES and matchRoute have cmdb routes.
# But the NAV array items 101-110 are the main navigation.

# Let me add new NAV entries for the new routes.
# I'll add them after line 101 (the cmdb entry) but within the staffOnly section.

# Actually, looking at the structure more carefully:
# - Lines 99-101: Assets, CMDB (staffOnly)
# - Lines 102-110: Procurement section

# The new routes I need to add are:
# - Report routes: #/reports/coverage, #/reports/verification_age, etc.
# - But these have '#' prefix, not '#/cmdb/...'

# Let me check what the visibleNav function does and where to insert.
# The NAV array items without 'section' are top-level nav items.

# I'll add the new routes as additional top-level nav items.
# Looking at the structure, I should add them before the 'Procurement' section.

# New NAV entries to add (after line 101, before line 102):
new_entries = [
    "  { hash: '#/reports/coverage', label: 'Coverage', staffOnly: true },\n",
    "  { hash: '#/reports/verification_age', label: 'Verification Age', staffOnly: true },\n",
    "  { hash: '#/reports/orphans', label: 'Orphans', staffOnly: true },\n",
    "  { hash: '#/reports/ownership_gaps', label: 'Ownership Gaps', staffOnly: true },\n",
    "  { hash: '#/reports/relationship_coverage', label: 'Relationship Coverage', staffOnly: true },\n",
    "  { hash: '#/reports/drift', label: 'Drift', staffOnly: true },\n",
    "  { hash: '#/reports/critical_deps', label: 'Critical Dependencies', staffOnly: true },\n",
    "  { hash: '#/reports/asset_sync', label: 'Asset Sync', staffOnly: true },\n",
    "  { hash: '#/reports/software_sync', label: 'Software Sync', staffOnly: true },\n",
    "  { hash: '#/verification', label: 'Verification Queue', staffOnly: true },\n",
    "  { hash: '#/services', label: 'Services', staffOnly: true },\n",
]

# Insert after line 101 (index 100), which is the cmdb entry
# Actually, let me insert after the cmdb entry but before assets
# Line 101 is the cmdb entry, line 102 starts the section

# Let me find the exact insertion point
cmdb_line = 101  # 0-indexed: 100
# I want to insert after line 101 (the cmdb entry), so at index 101 (after the cmdb line)
# But the new entries should go between cmdb and assets

# Actually, let me just insert at position 101 (after the cmdb entry at index 100)
insert_at = 101  # This will insert after line 101 (0-indexed), pushing everything down

# Wait, the lines list is 0-indexed. Line 101 in the file is at index 100.
# I want to insert after the cmdb entry, so at position 101 (after the cmdb line).

# Let me just use string replacement or insertion
# I'll insert after the cmdb entry

# The cmdb entry is at lines[100] (0-indexed)
# I want to insert new entries after it, before line 102 (assets)

# Let me just insert at position 101 (which is currently line 102, the assets entry)
# No wait - I need to be more careful.

# Let me find the actual indices
for i, line in enumerate(lines[:115]):
    if 'cmdb' in line.lower() and 'hash' in line.lower():
        print(f'Found cmdb entry at line {i+1}: {line.rstrip()}')
    if '#assets' in line and 'hash' in line:
        print(f'Found assets entry at line {i+1}: {line.rstrip()}')

# Based on earlier output, cmdb is at line 101, assets at line 99
# Actually from earlier: Line 99: { hash: '#/assets', label: 'Assets', staffOnly: true },
# Line 100: (empty or something)
# Line 101: { hash: '#/cmdb', label: 'CMDB', staffOnly: true },

# Wait, that doesn't match. Let me re-check.
for i in range(98, 105):
    print(f'Line {i+1}: {lines[i].rstrip()}')
"