from django.contrib import admin
from .models import ConfigurationItemType, ConfigurationItem, ConfigurationItemRelationship, ConfigurationBaseline, ConfigurationDriftFinding, ConfigurationItemHistory
admin.site.register(ConfigurationItemType)
admin.site.register(ConfigurationItem)
admin.site.register(ConfigurationItemRelationship)
admin.site.register(ConfigurationBaseline)
admin.site.register(ConfigurationDriftFinding)
admin.site.register(ConfigurationItemHistory)
