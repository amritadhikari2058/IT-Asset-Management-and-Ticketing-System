with open(r'common\import_stream.py', 'r') as f:
    content = f.read()

checks = [
    ('iter_uploaded_rows', 'iter_uploaded_rows' in content),
    ('batches(', 'batches(' in content),
    ('skip_empty_xlsx_rows', 'skip_empty_xlsx_rows' in content),
    ('skip_empty_csv_rows', 'skip_empty_csv_rows' in content),
    ('strip_empty_xlsx_values', 'strip_empty_xlsx_values' in content),
    ('reject_duplicate_headers', 'reject_duplicate_headers' in content),
    ('count_uploaded_rows', 'count_uploaded_rows' in content),
]

print('Key import_stream.py patterns:')
for name, result in checks:
    status = 'OK' if result else 'MISSING'
    print(f'  {name}: {status}')