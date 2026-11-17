#!/usr/bin/env python
import re
import sys
sys.path.insert(0, '.')

files = [
    'backend/monitoring/test_models.py',
    'backend/monitoring/test_authentication.py',
    'backend/monitoring/test_correlation.py',
]

for f in files:
    try:
        with open(f, 'r') as fh:
            content = fh.read()
        count = len(re.findall(r'def test_\(', content))
        print(f'{f}: {count} test methods')
    except Exception as e:
        print(f'{f}: ERROR - {e}')

# Also check for test_ingestion.py
import os
ing = 'backend/monitoring/test_ingestion.py'
if os.path.exists(ing):
    with open(ing, 'r') as fh:
        content = fh.read()
    count = len(re.findall(r'def test_\(', content))
    print(f'{ing}: {count} test methods')
else:
    print(f'{ing}: DOES NOT EXIST')