from django.contrib import admin
from .models import (
    ProcurementSetting, PurchaseRequest, PurchaseRequestItem, PurchaseQuotation,
    PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem, ProcurementHistory
)

admin.site.register(ProcurementSetting)
admin.site.register(PurchaseRequest)
admin.site.register(PurchaseRequestItem)
admin.site.register(PurchaseQuotation)
admin.site.register(PurchaseOrder)
admin.site.register(PurchaseOrderItem)
admin.site.register(GoodsReceipt)
admin.site.register(GoodsReceiptItem)
admin.site.register(ProcurementHistory)
