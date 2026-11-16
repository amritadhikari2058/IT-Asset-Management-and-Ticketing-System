"""Fix ASSET_MODEL references."""
content = open('backend/monitoring/models.py').read()
content = content.replace('settings.ASSET_MODEL or "assets.Asset"', '"assets.Asset"')
open('backend/monitoring/models.py', 'w').write(content)
print('Done')