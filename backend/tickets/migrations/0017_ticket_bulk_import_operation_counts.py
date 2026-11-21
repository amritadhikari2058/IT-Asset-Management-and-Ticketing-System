# Generated manually for operational observability of ticket bulk imports.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0016_ticket_bulk_import_operation'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticketbulkimportoperation',
            name='failed_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='ticketbulkimportoperation',
            name='processed_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='ticketbulkimportoperation',
            name='successful_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='ticketbulkimportoperation',
            name='total_rows',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
