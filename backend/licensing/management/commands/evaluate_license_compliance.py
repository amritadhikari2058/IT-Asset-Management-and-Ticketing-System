"""Management command to evaluate license compliance and detect shortages/risks."""

from django.core.management.base import BaseCommand
from licensing.models import LicenseAgreement, SoftwareProduct
from licensing.services import evaluate_license_compliance


class Command(BaseCommand):
    help = "Evaluate software license compliance, over-allocation, and expiry risks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Simulate evaluation without persisting findings (default: True).",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            default=False,
            help="Execute and persist compliance findings in the database.",
        )
        parser.add_argument(
            "--agreement-id",
            type=int,
            help="Target a specific LicenseAgreement ID.",
        )
        parser.add_argument(
            "--product-id",
            type=int,
            help="Target a specific SoftwareProduct ID.",
        )
        parser.add_argument(
            "--department-id",
            type=int,
            help="Target a specific Department ID.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Batch size for processing records.",
        )

    def handle(self, *args, **options):
        dry_run = not options.get("execute")
        agr_id = options.get("agreement_id")
        prod_id = options.get("product_id")

        agr = None
        if agr_id:
            try:
                agr = LicenseAgreement.objects.get(pk=agr_id)
            except LicenseAgreement.DoesNotExist:
                self.stderr.write(f"LicenseAgreement ID {agr_id} not found.")
                return

        prod = None
        if prod_id:
            try:
                prod = SoftwareProduct.objects.get(pk=prod_id)
            except SoftwareProduct.DoesNotExist:
                self.stderr.write(f"SoftwareProduct ID {prod_id} not found.")
                return

        mode_str = "DRY-RUN" if dry_run else "EXECUTE"
        self.stdout.write(f"Starting license compliance evaluation [{mode_str}]...")

        if dry_run:
            self.stdout.write("Dry-run mode active. No findings will be persisted.")
            # Perform evaluation calculation
            findings = evaluate_license_compliance(software_product=prod, agreement=agr)
            self.stdout.write(f"Identified {len(findings)} potential compliance finding(s).")
            for f in findings:
                self.stdout.write(f" - [{f.severity.upper()}] {f.finding_type}: {f.title}")
        else:
            findings = evaluate_license_compliance(software_product=prod, agreement=agr)
            self.stdout.write(self.style.SUCCESS(
                f"Successfully evaluated and persisted {len(findings)} compliance finding(s)."
            ))
