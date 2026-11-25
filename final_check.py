#!/usr/bin/env python3
import sys

with open('D:\\\\IT-Asset-Management-and-Ticketing-System\\\\frontend\\\\src\\\\App.jsx', 'r') as f:
    content = f.read()

checks = {
    'reports/coverage': "'#reports/coverage': <AssetReportsPage />," in content,
    'verification': "'#verification': <VerificationQueuePage />," in content,
    'Reports section': "section: 'Reports'" in content,
    'services graph check': "route.startswith('#/services/') and route.match('/graph$')" in content,
}

for name, result in checks.items():
    status = 'PRESENT' if result else 'MISSING'
    print(f'{status}: {name}')