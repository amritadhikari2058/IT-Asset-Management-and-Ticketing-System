#!/usr/bin/env python3
with open('D:\\\\IT-Asset-Management-and-Ticketing-System\\\\frontend\\\\src\\\\App.jsx', 'r') as f:
    content = f.read()

# The matchRoute function flow:
# 1. Line 327: if route.startsWith('#/monitoring')
# 2. Line 335: if route.startsWith('#/cmdb')
# 3. Line 353-355: if route.startsWith('#/services/')
# 4. Line 357: if route.startsWith('#/problem-management')
# 5. Lines 362-374: ticket checks
# Lines 375-390: asset/vendor/user checks
# Line 407: procurement checks
# Line 410: licensing checks
# Lines 413-455: routes object (THIS IS WHERE #/reports/ entries ARE)
# Line 456: return TITLES[h] ?? 'Tickets' (FALLBACK)

print('=== ROUTING FLOW ANALYSIS ===')
print()
print('1. #/monitoring check - #/reports/coverage does NOT start with #/monitoring')
print('2. #/cmdb check - #/reports/coverage does NOT start with #/cmdb')
print('3. #/services/ check - #/reports/coverage does NOT start with #/services/')
print('3b. #/services/ graph/impact/spof - THESE WERE ADDED BUT for #/services/*, not #/reports/*')
print('4. #/problem-management check - #/reports/coverage does NOT start with #/problem-management')
print('5. Ticket checks - #/reports/coverage does not match any ticket pattern')
print('6. Asset/vendor checks - NO')
print('7. Procurement checks - NO')
print('8. Licensing checks - NO')
print()
print('9. routes object - #/reports/coverage IS PRESENT: YES')
print()
print('10. Fallback - TITLES[h] ?? \\'Tickets\\'')
print()
print('=== KEY INSIGHT ===')
print('The routes object is checked AFTER all the startsWith checks')
print('#/reports/coverage will NOT match any earlier check')
print('It SHOULD fall through to the routes object')
print('Then SHOULD find #/reports/coverage: <AssetReportsPage />')
print('Then SHOULD NOT reach the fallback Tickets')
print()
print('BUT: There might be an issue with HOW the hash is constructed')
print('In the Shell component (line 458):')
print('const hash = routerLocation.pathname === \\'\\'\\' ? \\'#/tickets\\' : `#${routerLocation.pathname}${routerLocation.search}`;')
print()
print('This constructs the hash from the pathname.')
print('If the backend API returns /api/cmdb/reports/... the frontend')
print('would navigate to #/cmdb/reports (from the NAV)')
print()
print('=== VERIFY: Check the NAV hash values ===')
# Check the NAV entries
import re
nav_entries = re.findall(r'"hash":\\s*\"#\\w[^\"]*\"', content)
print(f'Found {len(nav_entries)} hash entries in NAV')
# Show ones with /reports/
for entry in nav_entries:
    if '/reports/' in entry:
        print(f'  NAV entry: {entry}')