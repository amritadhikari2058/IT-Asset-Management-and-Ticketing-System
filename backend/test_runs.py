import sys
sys.path.insert(0, 'D:\\IT-Asset-Management-and-Ticketing-System\\backend')
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
import django
django.setup()

from common.models import ScheduledReportRun, ScheduledReport
import uuid

# Try creating two runs with same scheduled_report but different occurrence_id
sr = ScheduledReport.objects.first()
if not sr:
    print("No ScheduledReport found")
    sys.exit(1)

# Generate unique occurrence_ids
occ1 = str(uuid.uuid4())
occ2 = str(uuid.uuid4())

run1 = ScheduledReportRun.objects.create(
    scheduled_report=sr, status="running", success=False,
    execution_token="tok-1",
    lease_expires_at=None,
    last_heartbeat_at=None, occurrence_id=occ1
)
print(f"Run1 created: id={run1.id}, occurrence_id={run1.occurrence_id}")

try:
    run2 = ScheduledReportRun.objects.create(
        scheduled_report=sr, status="running", success=False,
        execution_token="tok-2",
        lease_expires_at=None,
        last_heartbeat_at=None, occurrence_id=occ2
    )
    print(f"Run2 created: id={run2.id}, occurrence_id={run2.occurrence_id}")
except Exception as e:
    print(f"Error creating Run2: {e}")