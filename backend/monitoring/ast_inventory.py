#!/usr/bin/env python
import ast
from pathlib import Path

paths = [
    Path(r'backend/monitoring/test_models.py'),
    Path(r'backend/monitoring/test_authentication.py'),
    Path(r'backend/monitoring/test_correlation.py'),
]
ingestion = Path(r'backend/monitoring/test_ingestion.py')
if ingestion.exists():
    paths.append(ingestion)

grand_total = 0
for path in paths:
    source = path.read_text(encoding='utf-8-sig')
    tree = ast.parse(source, filename=str(path))
    print(f'FILE={path}')
    file_total = 0
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name.startswith('test_')
            ]
            print(f'CLASS={node.name}')
            print(f'CLASS_COUNT={len(methods)}')
            for method in methods:
                print(f'TEST={node.name}.{method}')
            file_total += len(methods)
    print(f'FILE_TOTAL={file_total}')
    grand_total += file_total
print(f'AST_TOTAL={grand_total}')