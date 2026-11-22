#!/usr/bin/env python
import socket
import subprocess
import sys
import time
import os

def check_port(port, host='127.0.0.1'):
    """Check if a port is open."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except:
        return False

def start_backend():
    """Start the Django backend server."""
    print("Starting Django backend...")
    proc = subprocess.Popen(
        [sys.executable, 'manage.py', 'runserver', '0:8000'],
        cwd=r'E:\OneDrive\Desktop\Ticket and Asset Management System\backend',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return proc

def start_frontend():
    """Start the Vite frontend server using full path to npx."""
    npx_path = r'E:\OneDrive\Desktop\Ticket and Asset Management System\frontend\node_modules\.bin\npx.cmd'
    print(f"Starting Vite frontend using: {npx_path}")
    proc = subprocess.Popen(
        [npx_path, 'vite', '--host', '0.0.0.0', '--port', '5173'],
        cwd=r'E:\OneDrive\Desktop\Ticket and Asset Management System\frontend',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return proc

print("=" * 60)
print("Checking port status...")
print("=" * 60)

port_5173 = check_port(5173)
port_8000 = check_port(8000)

print(f"Port 5173: {'OPEN' if port_5173 else 'CLOSED'}")
print(f"Port 8000: {'OPEN' if port_8000 else 'CLOSED'}")

print()
print("=" * 60)
print("Starting servers if needed...")
print("=" * 60)

servers_started = []

if not port_5173:
    print("Starting Vite frontend server...")
    frontend_proc = start_frontend()
    servers_started.append(('frontend', frontend_proc))
    time.sleep(5)
    port_5173 = check_port(5173)
    print(f"Port 5173 after start: {'OPEN' if port_5173 else 'CLOSED'}")

if not port_8000:
    print("Starting Django backend server...")
    backend_proc = start_backend()
    servers_started.append(('backend', backend_proc))
    time.sleep(5)
    port_8000 = check_port(8000)
    print(f"Port 8000 after start: {'OPEN' if port_8000 else 'CLOSED'}")

print()
print("=" * 60)
print("Final status...")
print("=" * 60)

print(f"Port 5173: {'OPEN' if port_5173 else 'CLOSED'}")
print(f"Port 8000: {'OPEN' if port_8000 else 'CLOSED'}")

if port_5173 and port_8000:
    print("\nBoth servers are running! Tests should now execute.")
else:
    print("\nNot all ports are open. Some servers may need manual startup.")
    print("Check the logs above for errors.")