import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rest_framework.views import APIView
import inspect

print(inspect.getsource(APIView.finalize_response))

