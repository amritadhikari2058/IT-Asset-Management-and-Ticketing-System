from celery import shared_task
from common.models import BackgroundTaskRun
from .services import sync_asset_to_ci, evaluate_configuration_drift
from .models import ConfigurationItem

@shared_task
def evaluate_configuration_drift_task():
    run = BackgroundTaskRun.objects.create(task_name="cmdb_drift", status="running")
    try:
        count = 0
        for ci in ConfigurationItem.objects.filter(is_deleted=False):
            evaluate_configuration_drift(ci)
            count += 1
        run.status = "success"
        run.result_summary = f"evaluated {count}"
        run.save(update_fields=["status","result_summary"])
    except Exception as e:
        run.status = "failed"
        run.error_message = str(e)[:500]
        run.save(update_fields=["status","error_message"])
    return run.id

@shared_task
def sync_assets_to_cmdb_task(batch_size=100):
    from assets.models import Asset
    run = BackgroundTaskRun.objects.create(task_name="cmdb_asset_sync", status="running")
    try:
        created = 0
        for asset in Asset.objects.filter(is_deleted=False)[:batch_size]:
            sync_asset_to_ci(asset)
            created += 1
        run.status = "success"
        run.result_summary = f"synced {created}"
        run.save(update_fields=["status","result_summary"])
    except Exception as e:
        run.status = "failed"
        run.error_message = str(e)[:500]
        run.save(update_fields=["status","error_message"])
    return run.id

@shared_task
def check_ci_verification_age_task():
    run = BackgroundTaskRun.objects.create(task_name="cmdb_verify_age", status="running")
    run.status = "success"
    run.result_summary = "done"
    run.save(update_fields=["status","result_summary"])
    return run.id
