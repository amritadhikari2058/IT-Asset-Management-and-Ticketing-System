#!/usr/bin/env python3
import os

base = r"D:\IT-Asset-Management-and-Ticketing-System\frontend\src"
app_file = os.path.join(base, "App.jsx")

with open(app_file, 'r', encoding='utf-8') as f:
    content = f.read()

# The exact string from the file at index 25088
target = "'#reports/schedules': <ScheduledReports />,"
print(f"Looking for target string: {repr(target)}")
idx = content.find(target)
print(f"Found at: {idx}")

if idx >= 0:
    # Found it - replace
    newStr = """'#reports/schedules': <ScheduledReports />,
    '#reports/coverage': <AssetReportsPage />,
    '#reports/verification_age': <VerificationQueuePage />,
    '#reports/orphans': <AssetReportsPage />,
    '#reports/ownership_gaps': <AssetReportsPage />,
    '#reports/relationship_coverage': <AssetReportsPage />,
    '#reports/drift': <DriftFindingsPage />,
    '#reports/critical_deps': <AssetReportsPage />,
    '#reports/asset_sync': <AssetReportsPage />,
    '#reports/software_sync': <AssetReportsPage />,
"""
    
    new_content = content.replace(target, newStr)
    with open(app_file, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Success: replacement done')
else:
    print('Target not found')
    # Show what's actually there around the reports/schedules areas
    idx1 = content.find('reports/schedules')
    print(f"First reports/schedules at: {idx1}")
    if idx1 >= 0:
        print(f"Context 1: {repr(content[idx1:idx1+50])}")
    idx2 = content.find('reports/schedules', idx1+1)
    print(f"Second reports/schedules at: {idx2}")
    if idx2 >= 0:
        print(f"Context 2: {repr(content[idx2:idx2+50])}")