import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, '.')
django.setup()

# Check installed apps
from config.settings import INSTALLED_APPS
print('=== INSTALLED APPS ===')
for app in INSTALLED_APPS:
    print(app)

print('\n=== MODEL COUNTS ===')
# Check models count for each app using Django app config
from django.apps import apps

for app_config in apps.get_app_configs():
    app_name = app_config.name
    # Skip Django core apps
    if app_name in ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
                    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles']:
        continue
    if app_name in ['rest_framework', 'rest_framework_simplejwt.token_blacklist', 'corsheaders']:
        continue
    # Skip config
    if app_name == 'config':
        continue
    
    try:
        models = list(app_config.get_models())
        model_count = len(models)
        print(f'{app_name}: {model_count} models - {[m.__name__ for m in models]}')
    except Exception as e:
        print(f'{app_name}: error - {type(e).__name__}: {e}')