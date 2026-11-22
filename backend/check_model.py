import sys
sys.path.insert(0, 'D:\\IT-Asset-Management-and-Ticketing-System\\backend')
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
import django
django.setup()

from common.models import ScheduledReportRun, ScheduledReport

# Check the model
print('ScheduledReportRun fields:')
for f in ScheduledReportRun._meta.fields:
    print(f'  {f.name}: {f.get_internal_type()}, unique={getattr(f, "unique", False)}, blank={f.blank}, null={f.null}')

print()
print('ScheduledReport foreign key on ScheduledReportRun:')
for f in ScheduledReportRun._meta.fields:
    if f.is_relation and f.related_model == ScheduledReport:
        print(f'  {f.name}: related_name={f.related_name}, null={f.null}')