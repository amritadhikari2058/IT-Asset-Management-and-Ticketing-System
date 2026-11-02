# Apply throttling to auth endpoints
path = r'D:\IT-Asset-Management-and-Ticketing-System\backend\accounts\auth_views.py'
with open(path, 'r') as f:
    content = f.read()

# Add imports
if 'throttle' not in content:
    content = content.replace('from rest_framework.response import Response\n',
        'from rest_framework.response import Response\nfrom rest_framework.throttling import AnonRateThrottle\n\nfrom common.throttling import AuthRateThrottle\n')

# Add throttle_classes to public endpoints
# password_reset_request
content = content.replace('@api_view(["POST"])\n@permission_classes([AllowAny])\ndef password_reset_request',
    '@api_view(["POST"])\n@permission_classes([AllowAny])\n@throttle_classes([AuthRateThrottle])\ndef password_reset_request')

# password_reset_confirm
content = content.replace('@api_view(["POST"])\n@permission_classes([AllowAny])\ndef password_reset_confirm',
    '@api_view(["POST"])\n@permission_classes([AllowAny])\n@throttle_classes([AuthRateThrottle])\ndef password_reset_confirm')

# verification_confirm
content = content.replace('@api_view(["GET"])\n@permission_classes([AllowAny])\ndef verification_confirm',
    '@api_view(["GET"])\n@permission_classes([AllowAny])\n@throttle_classes([AuthRateThrottle])\ndef verification_confirm')

with open(path, 'w') as f:
    f.write(content)
print('done')
