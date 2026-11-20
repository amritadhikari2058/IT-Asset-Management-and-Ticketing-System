"""Add reconciliation and allocation integrity finding types."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("licensing", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="licensecompliancefinding",
            name="finding_type",
            field=models.CharField(
                choices=[
                    ("over_allocated", "Over-Allocated Agreement"),
                    ("unlicensed_installation", "Unlicensed Installation"),
                    ("expired_agreement", "Expired License Agreement"),
                    ("expiring_agreement", "Expiring License Agreement"),
                    ("unused_license", "Potentially Unused License"),
                    ("duplicate_user_allocation", "Duplicate User Allocation"),
                    ("duplicate_device_allocation", "Duplicate Device Allocation"),
                    ("prohibited_software", "Prohibited Software Detected"),
                    ("unsupported_version", "Unsupported Version"),
                    ("missing_documentation", "Missing Required Documentation"),
                    ("missing_entitlement_quantity", "Missing Entitlement Quantity"),
                    ("renewal_overdue", "Renewal Overdue"),
                    ("allocation_to_inactive_user", "Allocation to Inactive Employee"),
                    ("allocation_to_retired_asset", "Allocation to Inactive/Retired Asset"),
                    ("terminated_agreement_allocation", "Allocation on Terminated Agreement"),
                    ("expired_agreement_allocation", "Allocation on Expired Agreement"),
                    ("inconsistent_allocation_state", "Inconsistent Allocation State"),
                ],
                db_index=True,
                max_length=60,
            ),
        ),
    ]
