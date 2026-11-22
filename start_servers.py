#!/usr/bin/env python
import subprocess
import time
import sys
import socket

def wait_for_port(port, host='127.0.0.1', timeout=60):
    """Wait until a port is accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect((host, port))
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False

print("=" * 60)
print("Starting Django Backend Server...")
print("=" * 60)

backend_proc = subprocess.Popen(
    [sys.executable, 'manage.py', 'runserver', '0:8000'],
    cwd=r'E:\OneDrive\Desktop\Ticket and Asset Management System\backend',
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

if wait_for_port(8000):
    print("Backend is ready on http://127.0.0.1:8000")
else:
    print("Warning: Backend may not be ready on port 8000")
    print("Backend stderr:", backend_proc.stderr.read().decode('utf-8', errors='replace')[:500])

print()
print("=" * 60)
print("Starting Vite Frontend Server...")
print("=" * 60)

frontend_proc = subprocess.Popen(
    ['npx', 'vite', '--host', '0.0.0.0', '--port', '5173'],
    cwd=r'E:\OneDrive\Desktop\Ticket and Asset Management System\frontend',
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

if wait_for_port(5173):
    print("Frontend is ready on http://0.0.0.0:5173")
else:
    print("Warning: Frontend may not be ready on port 5173")
    print("Frontend stderr:", frontend_proc.stderr.read().decode('utf-8', errors='replace')[:500])

print()
print("=" * 60)
print("Both servers started. Press Ctrl+C to stop.")
print("=" * 60)

try:
    while True:
        time.sleep(10)
        # Check if processes are still running
        if backend_proc.poll() is not None:
            print("Backend process has ended")
        if frontend_proc.poll() is not None:
            print("Frontend process has ended")
except KeyboardInterrupt:
    print()
    print("Stopping servers...")
    backend_proc.terminate()
    frontend_proc.terminate()
    backend_proc.wait()
    frontend_proc.wait()
    print("Servers stopped.")