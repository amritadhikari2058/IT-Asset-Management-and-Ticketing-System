# Generated manually for durable per-row ticket bulk import outcomes.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0017_ticket_bulk_import_operation_counts'),
    ]

    operations = [
        migrations.CreateModel(
            name='TicketBulkImportRowOutcome',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('row_index', models.PositiveIntegerField(help_text='0-based index in the normalized import row sequence.')),
                ('row_number', models.PositiveIntegerField(help_text='1-based row number reported by the import API.')),
                ('row_fingerprint', models.CharField(blank=True, default='', help_text='SHA-256 of the canonical normalized row payload (evidence only).', max_length=64)),
                ('outcome', models.CharField(choices=[('succeeded', 'Succeeded'), ('failed', 'Failed')], max_length=20)),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('operation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='row_outcomes', to='tickets.ticketbulkimportoperation')),
                ('ticket', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bulk_import_row_outcomes', to='tickets.ticket')),
            ],
            options={
                'ordering': ['operation', 'row_index'],
            },
        ),
        migrations.AddConstraint(
            model_name='ticketbulkimportrowoutcome',
            constraint=models.UniqueConstraint(fields=('operation', 'row_index'), name='uniq_tbi_row_outcome_op_idx'),
        ),
        migrations.AddIndex(
            model_name='ticketbulkimportrowoutcome',
            index=models.Index(fields=['operation', 'outcome'], name='tbi_row_outcome_op_out_idx'),
        ),
        migrations.AddIndex(
            model_name='ticketbulkimportrowoutcome',
            index=models.Index(fields=['ticket'], name='tbi_row_outcome_ticket_idx'),
        ),
    ]
