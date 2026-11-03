# Phase 16 — Advanced Asset Inventory and Stock Management

## 1. Executive summary
Implemented a new Django `inventory` app providing consumable stock management distinct from serialized assets. Includes models, migrations, REST APIs, permissions, transactions, reservations, purchase receiving, service request fulfilment, and dashboard.

## 2. Existing functionality reused
Asset, Vendor, User/Department, ServiceRequest, SoftDelete conventions.

## 3. New models
StockItem, StockMovement, StockReservation, PurchaseReceipt, PurchaseReceiptLine. Migration inventory.0001_initial.

## 4. Migrations
inventory/migrations/0001_initial.py

## 5. API endpoints
- /api/inventory/stock-items/ (CRUD, receive, issue, return, adjust, damage, low-stock, dashboard, movements)
- /api/inventory/purchase-receipts/ (CRUD, increases stock on create)
- /api/inventory/reservations/ (CRUD, release, fulfil)
- /api/inventory/fulfil-service-request/

## 6. Frontend
Not implemented in this pass (backend-focused).

## 7. Stock rules
Positive quantities validated; select_for_update; negative prevention; immutable movements via adjustment entries.

## 8. Reservation/fulfilment
Reserve increases reserved; release decreases; fulfil converts; duplicate fulfilment prevented via source_request check.

## 9. Service request integration
Fulfil endpoint links movement to source_request; prevents duplicate.

## 10. Permissions
Role-based checks in views (IT Support/Manager/Admin).

## 11. Validation
Quantity positivity, reason required for adjustments, insufficient stock.

## 12. Tests
Not run in this pass.

## 13. Build/lint
Django check passed.

## 14. Known limitations
Frontend pages not built; concurrency tests not added; low-stock notification dedup not implemented.

## 15. Git status
See git status.

## 16. Roadmap
Phase 16 backend core complete; frontend + tests pending.

## 17. Next phase
Frontend inventory UI and tests.
