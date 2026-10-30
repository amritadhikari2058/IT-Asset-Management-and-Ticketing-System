import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import inspect
from rest_framework.negotiation import DefaultContentNegotiation

print(inspect.getsource(DefaultContentNegotiation.select_renderer))
print(inspect.getsource(DefaultContentNegotiation.filter_renderers))
from rest_framework.renderers import BaseRenderer, JSONRenderer, CSVRenderer
print("BaseRenderer.format:", BaseRenderer.format)
print("JSONRenderer.format:", JSONRenderer().format, "CSV:", CSVRenderer().format)

