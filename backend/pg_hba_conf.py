#!/usr/bin/env python
import os
# Use local socket connection (peer authentication on Linux, but on Windows may need different approach)
# For now, just test with environment variables that worked before

import django
from django.conf import settings

# Check current database config
print("Current DATABASES setting:")
print(settings.DATABASES)
"