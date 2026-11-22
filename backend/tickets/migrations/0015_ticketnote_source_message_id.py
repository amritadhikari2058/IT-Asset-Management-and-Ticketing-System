# Generated manually for Phase E.4 inbound reply-note idempotency.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0014_ticketattachment_source_identity'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticketnote',
            name='source_message_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Message-ID of the inbound email this note came from',
                max_length=255,
            ),
        ),
        migrations.AddConstraint(
            model_name='ticketnote',
            constraint=models.UniqueConstraint(
                condition=models.Q(source_message_id__gt=''),
                fields=('source_message_id',),
                name='uniq_ticketnote_source_message',
            ),
        ),
    ]
