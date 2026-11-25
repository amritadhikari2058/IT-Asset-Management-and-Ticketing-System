#!/usr/bin/env python3
import sys

with open('D:\\\\IT-Asset-Management-and-Ticketing-System\\\\frontend\\\\src\\\\App.jsx', 'r') as f:
    content = f.read()

# Systematically check each routing element
checks = {
    'routes object #/reports/coverage': "'#reports/coverage': <AssetReportsPage />," in content,
    'routes object #/verification': "'#verification': <VerificationQueuePage />," in content,
    'matchRoute #/services/ graph': "route.startswith('#/services/') and route.match('/graph$')" in content,
    'matchRoute #/services/ impact': "route.startswith('#/services/') and route.match('/impact$')" in content,
    'matchRoute #/services/ spof': "route.startswith('#/services/') and route.match('/single-points-of-failure$')" in content,
    'NAV Reports section': "section: 'Reports'" in content,
    'NAV coverage entry': "'#reports/coverage', label: 'Coverage'" in content,
    'NAV verification entry': "'#verification', label: 'Verification Queue'" in content,
}

print('ROUTING CHECKS:')
for desc, result in checks.items():
    status = 'OK' if result else 'MISSING'
    print(f'  {status} {desc}')

print()
print('=== #/reports/coverage routing path ===')
print('1. #/monitoring? NO (starts with #/reports/)')
print('2. #/cmdb? NO (starts with #/reports/)')
print('3. #/services/ check? NO (starts with #/reports/)')
print('4. #/problem-management? NO')
print('5. Ticket checks? NO')
print('6. Asset/vendor checks? NO')
print('7. Procurement checks? NO')
print('8. Licensing checks? NO')
print('9. routes object? YES - should find #/reports/coverage')
print()
print('Routes object contains #/reports/coverage:', "'#reports/coverage': <AssetReportsPage />," in content)