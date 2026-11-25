#!/usr/bin/env python3
with open('D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\App.jsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with 'if (route.startsWith(#/problem-management))' and insert before it
# Actually, let me find the cmdb routes block end and add after it

# Look for the line that closes the cmdb routes block
for i, line in enumerate(lines):
    if 'if (route.startsWith('#/cmdb')) {' in line:
        print(f"Found cmdb start at line {i+1}")
    if 'return <CmdbDashboard />;' in line or 'return <CmdbDashboard />' in line:
        print(f"Found CmdbDashboard at line {i+1}: {line.rstrip()}")

# Let me just insert before the #/problem-management check
# Find line 342 area
for i in range(338, 345):
    print(f"Line {i+1}: {lines[i].rstrip()}")