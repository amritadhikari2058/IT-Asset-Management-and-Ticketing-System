#!/usr/bin/env python3
import os

base = r"D:\IT-Asset-Management-and-Ticketing-System\frontend\src"
app_file = os.path.join(base, "App.jsx")

with open(app_file, 'r') as f:
    content = f.read()

# The routes object has '#reports/schedules': <ScheduledReports />,
# The TITLES object has '#reports/schedules': 'Scheduled reports',
# We want to add after the routes object version

# Find the routes object version
oldStr = "'#reports/schedules': <ScheduledReports />,"
idx = content.find(oldStr)
print(f"Found routes object at: {idx}")

if idx >= 0:
    # Found it in routes object - replace
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
    
    new_content = content.replace(oldStr, newStr)
    with open(app_file, 'w') as f:
        f.write(new_content)
    print('Success: replacement done in routes object')
else:
    print('routes oldStr not found')
    # Try the TITLES object version
    oldStr2 = "'#reports/schedules': 'Scheduled reports',"
    idx2 = content.find(oldStr2)
    print(f"Found TITLES object at: {idx2}")
    if idx2 >= 0:
        print('Would need different approach for TITLES object')