"""Evaluate configuration drift against approved baselines.

Dry-run by default: use --execute to write findings. Evaluation is
idempotent (deterministic fingerprints) and auto-resolves stale findings.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Evaluate CMDB configuration drift against approved baselines."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be evaluated without writing (default).",
        )
        group.add_argument(
            "--execute", action="store_true",
            help="Actually run the evaluation and record findings.",
        )
        parser.add_argument("--ci-id", type=int,
                            help="Evaluate only this configuration item.")
        parser.add_argument("--baseline-id", type=int,
                            help="Evaluate only against this baseline.")
        parser.add_argument("--service-id", type=int,
                            help="Evaluate CIs linked to this service only.")
        parser.add_argument(
            "--batch-size", type=int, default=100,
            help="Maximum number of CIs to evaluate (default 100).",
        )

    def handle(self, *args, **options):
        from cmdb.baselines import evaluate_configuration_drift
        from cmdb.models import (
            ConfigurationBaseline,
            ConfigurationDriftFinding,
            ConfigurationItem,
            ServiceConfigurationItemLink,
        )

        execute = options["execute"]
        batch = max(int(options["batch_size"] or 100), 1)

        # Only CIs covered by approved baselines can produce findings.
        baseline = None
        if options.get("baseline_id"):
            baseline = ConfigurationBaseline.objects.filter(
                id=options["baseline_id"], status="approved",
                is_deleted=False,
            ).first()
            if baseline is None:
                self.stderr.write(
                    f"Baseline {options['baseline_id']} not found or not "
                    f"approved."
                )
                return

        qs = ConfigurationItem.objects.filter(
            is_deleted=False, baselines__status="approved",
            baselines__is_deleted=False,
        ).distinct().order_by("id")
        if options.get("ci_id"):
            qs = qs.filter(id=options["ci_id"])
        if options.get("service_id"):
            linked_ids = ServiceConfigurationItemLink.objects.filter(
                service_id=options["service_id"], is_deleted=False,
            ).values_list("configuration_item_id", flat=True)
            qs = qs.filter(id__in=list(linked_ids))
        if baseline is not None:
            qs = qs.filter(baselines=baseline)
        qs = qs[:batch]

        open_before = ConfigurationDriftFinding.objects.filter(
            is_deleted=False, status__in=("open", "acknowledged"),
        ).count()

        evaluated = 0
        detected = 0
        for ci in qs:
            if not execute:
                evaluated += 1
                continue
            found = evaluate_configuration_drift(
                ci,
                baseline=baseline,
                resolve_stale=True,
            )
            evaluated += 1
            detected += len(found)

        if execute:
            open_after = ConfigurationDriftFinding.objects.filter(
                is_deleted=False, status__in=("open", "acknowledged"),
            ).count()
            self.stdout.write(self.style.SUCCESS(
                f"evaluated: {evaluated}, findings returned: {detected}, "
                f"open findings: {open_before} -> {open_after}"
            ))
        else:
            self.stdout.write(
                f"DRY RUN: would evaluate: {evaluated} CI(s) against "
                f"approved baselines; open findings now: {open_before}"
            )
            self.stdout.write(self.style.WARNING(
                "Dry run only. Use --execute to record findings.",
            ))
