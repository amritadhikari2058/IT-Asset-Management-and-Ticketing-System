from django.db import models
from django.db.models import Q, F

c = models.CheckConstraint(condition=~Q(source_ticket=models.F("target_ticket")), name="test")
print("OK")