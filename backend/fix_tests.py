import re

with open('D:/IT-Asset-Management-and-Ticketing-System/backend/common/test_scheduled_report_delivery.py', 'r') as f:
    content = f.read()

# Fix 1: test_different_runs_same_recipient_distinct_identities - change run2 status from 'running' to 'pending'
# The pattern is: run2 = ScheduledReportRun.objects.create(
#    scheduled_report=sr, status="running", success=False,
content = content.replace(
    'run2 = ScheduledReportRun.objects.create(\n            scheduled_report=sr, status="running", success=False,\n            execution_token="tok-2",',
    'run2 = ScheduledReportRun.objects.create(\n            scheduled_report=sr, status="pending", success=False,\n            execution_token="tok-2",'
)

# Fix 2: test_smtp_accept_then_crash_before_sent - change second run status from 'running' to 'pending'
# Looking at the test, the second run at line 472
content = content.replace(
    'new_run = ScheduledReportRun.objects.create(\n            scheduled_report=sr, status="running", success=False,\n            execution_token="tok-d",',
    'new_run = ScheduledReportRun.objects.create(\n            scheduled_report=sr, status="pending", success=False,\n            execution_token="tok-d",'
)

with open('D:/IT-Asset-Management-and-Ticketing-System/backend/common/test_scheduled_report_delivery.py', 'w') as f:
    f.write(content)

print("Fixed test files")