# Generated manually for Phase E.3 inbound attachment identity.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0013_ticketattachment_content_hash'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticketattachment',
            name='source_message_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Message-ID of the inbound email this attachment came from',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='ticketattachment',
            name='source_part_index',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Deterministic MIME attachment ordinal within the source email',
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name='ticketattachment',
            constraint=models.UniqueConstraint(
                condition=(
                    models.Q(source_message_id__gt='')
                    & models.Q(source_part_index__isnull=False)
                ),
                fields=('source_message_id', 'source_part_index'),
                name='uniq_ticketattach_source_part',
            ),
        ),
    ]
