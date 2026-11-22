# Ensure 1-based row_number values for durable bulk import row outcomes.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0018_ticketbulkimportrowoutcome"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="ticketbulkimportrowoutcome",
            constraint=models.CheckConstraint(
                condition=models.Q(row_number__gte=1),
                name="tbi_row_outcome_row_number_gte_1",
            ),
        ),
    ]
