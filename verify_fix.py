#!/usr/bin/env python3
import sys

with open('D:\\\\IT-Asset-Management-and-Ticketing-System\\\\frontend\\\\src\\\\App.jsx', 'r') as f:
    content = f.read()

# Check for the new report route handlers
import re

# Find all 'if (route ===' lines
matches = re.findall(r"if \(route === '([^']+)'\)", content)
print("Report route handlers found:")
for m in matches:
    if '/reports/' in m or 'verification' in m:
        print(f'  {m}')

# Find all 'route.startsWith' lines
matches2 = re.findall(r"route\.startsWith\('(#/[^']+)'\)", content)
print("\nService route startsWith checks found:")
for m in matches2:
    if '/services/' in m:
        print(f'  {m}')

# Find 'single-points-of-failure'
if 'single-points-of-failure' in content:
    print("\n✅ single-points-of-failure handler PRESENT")
else:
    print("\n❌ single-points-of-failure handler MISSING")

# Find the new NAV section
if "section: 'Reports'" in content:
    print("✅ Reports nav section PRESENT")
else:
    print("❌ Reports nav section MISSING")

print("\n--- Summary ---")
print(f"Total 'if (route ===' lines with report/verification: {len([m for m in matches if '/reports/' in m or 'verification' in m])}")
print(f"Total 'route.startsWith' service lines: {len([m for m in matches2 if '/services/' in m])}")