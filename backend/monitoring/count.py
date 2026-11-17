import ast
from pathlib import Path

files = [
    "backend/monitoring/test_models.py",
    "backend/monitoring/test_authentication.py",
    "backend/monitoring/test_correlation.py",
]

ing = "backend/monitoring/test_ingestion.py"
import os
if os.path.exists(ing):
    files.append(ing)

for f in files:
    try:
        with open(f, 'r') as fh:
            content = fh.read()
        tree = ast.parse(content, filename=f)
        total = 0
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                methods = [child.name for child in node.body 
                           if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and child.name.startswith('test_')]
                print(f'{f}: CLASS_COUNT={len(methods)}')
                for m in methods:
                    print(f'  TEST={node.name}.{m}')
                total += len(methods)
        print(f'{f}: TOTAL={total}')
    except Exception as e:
        print(f'{f}: ERROR {e}')

print(f'GRAND_TOTAL: sum of above')