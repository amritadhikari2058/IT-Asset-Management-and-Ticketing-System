#!/usr/bin/env python
import os
import sys

# Add the backend directory to path
backend_dir = 'D:/IT-Asset-Management-and-Ticketing-System/backend'
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

os.chdir(backend_dir)

# Run the Django test
os.system('python manage.py test monitoring.test_models --verbosity 2 --keepdb --noinput')