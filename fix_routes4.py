#!/usr/bin/env python3
with open('D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\App.jsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with '#reports/schedules': <ScheduledReports />
for i, line in enumerate(lines):
    if "'#reports/schedules': <ScheduledReports />," in line:
        print(f"Found at line {i+1}: {line.rstrip()}")
        # Insert after this line
        new_lines = [
            "    '#reports/coverage': <AssetReportsPage />,\n",
            "    '#reports/verification_age': <VerificationQueuePage />,\n",
            "    '#reports/orphans': <AssetReportsPage />,\n",
            "    '#reports/ownership_gaps': <AssetReportsPage />,\n",
            "    '#reports/relationship_coverage': <AssetReportsPage />,\n",
            "    '#reports/drift': <DriftFindingsPage />,\n",
            "    '#reports/critical_deps': <AssetReportsPage />,\n",
            "    '#reports/asset_sync': <AssetReportsPage />,\n",
            "    '#reports/software_sync': <AssetReportsPage />,\n",
        ]
        # Insert after this line
        new_content = lines[:i+1] + new_lines + lines[i+1:]
        with open('D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\App.jsx', 'w', encoding='utf-8') as f:
            f.writelines(new_content)
        print("Success: inserted new report routes")
        break
else:
    print("Could not find the target line")