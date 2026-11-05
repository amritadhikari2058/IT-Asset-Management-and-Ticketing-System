"""Add optional Ticket category to ServiceCatalogueItem for auto ticket creation.

A catalogue item that creates a linked Ticket (``creates_ticket=True``) must
declare which ``TicketCategory`` the generated Ticket should use. The field is
nullable so existing catalogue items and items that do not create Tickets
remain valid; serializer validation enforces presence when ``creates_ticket``
is True. Uses PROTECT so a referenced TicketCategory cannot be hard-deleted
while a catalogue item still points at it.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0001_initial"),
        ("tickets", "0009_remove_automationrule_created_by_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicecatalogueitem",
            name="ticket_category",
            field=models.ForeignKey(
                blank=True,
                help_text="Ticket category used when this catalogue item creates a linked Ticket. Required when creates_ticket is True.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="service_catalogue_items",
                to="tickets.ticketcategory",
            ),
        ),
    ]
