#!/usr/bin/env python3
with open('D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\App.jsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the position to insert '#verification' route - after '#reports/software_sync'
old = "    '#reports/software_sync': <AssetReportsPage />,"
new = """    '#reports/software_sync': <AssetReportsPage />,
    '#verification': <VerificationQueuePage />,"""

if old in content:
    new_content = content.replace(old, new, 1)
    with open('D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\App.jsx', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Success: added #/verification route")
else:
    print("old string not found")
    # Show what's around that area
    idx = content.find("software_sync")
    print(f"Found software_sync at: {idx}")
    if idx >= 0:
        print(f"Context: {repr(content[idx:idx+60])}")