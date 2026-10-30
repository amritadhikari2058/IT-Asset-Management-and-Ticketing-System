import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import inspect
from rest_framework.decorators import api_view
print(inspect.getsource(api_view))

