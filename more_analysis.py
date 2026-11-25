#!/usr/bin/env python3
with open('D:\\\\IT-Asset-Management-and-Ticketing-System\\\\frontend\\\\src\\\\App.jsx', 'r') as f:
    content = f.read()

# Check for hash entries with /reports/
import re
nav_entries = re.findall(r'"hash":\s*"#\w[^"]*"', content)
reports_entries = [e for e in nav_entries if '/reports/' in entry]
print(f'Found {len(nav_entries)} hash entries in NAV')
print(f'Found {len(reports_entries)} reports entries in NAV')
for entry in reports_entries:
    print(f'  NAV entry: {entry}')

# Check the hash construction line
print()
print('=== Hash construction ===')
# Find the line that constructs hash
for i, line in enumerate(content.split('\\n')):
    if 'routerLocation.pathname' in line:
        print(f'Line {i+1}: {line}')
        # Show next line
        print(f'Line {i+2}: {content.split("\\n")[i+1] if i+1 < len(content.split("\\n")) else ""}')
        break

# Check the TITLES object
print()
print('=== TITLES object routes ===')
titles_matches = re.findall(r"'#\\w[^']*':\\s*\\w+", content)
# Filter for reports
for m in titles_matches:
    if '/reports/' in m or 'verification' in m:
        print(f'  Titles: {m}')