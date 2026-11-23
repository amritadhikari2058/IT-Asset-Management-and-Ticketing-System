"""URL configuration for the Backup & DR app."""
from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter()
router.register("schedules", views.BackupScheduleViewSet, basename="backupschedule")
router.register("jobs", views.BackupJobViewSet, basename="backupjob")
router.register("restore-points", views.RestorePointViewSet, basename="restorepoint")

urlpatterns = [
    path("", include(router.urls)),
]
