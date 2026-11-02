from django.conf import settings
from django.db import connections
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([AllowAny])
def health(request):
    """Liveness probe - always returns 200 if the app is running."""
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([AllowAny])
def ready(request):
    """Readiness probe - checks database connectivity."""
    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
        db_ok = True
    except Exception:
        db_ok = False

    status_code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return Response({
        'status': 'ready' if db_ok else 'not_ready',
        'database': 'ok' if db_ok else 'error',
    }, status=status_code)
