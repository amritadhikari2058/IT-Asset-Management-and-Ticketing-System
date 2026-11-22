#!/usr/bin/env python
import subprocess
import sys

result = subprocess.run(
    [sys.executable, '-m', 'playwright', 'test', 'e2e/auth.spec.js'],
    cwd=r'E:\OneDrive\Desktop\Ticket and Asset Management System\frontend',
    capture_output=True,
    text=True
)

print('Exit code:', result.returncode)
print('STDOUT:')
print(result.stdout)
print('STDERR:')
print(result.stderr)