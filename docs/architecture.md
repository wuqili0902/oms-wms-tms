# System Architecture — OMS-WMS-TMS

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy async + PostgreSQL 16 + Redis 7
- **Task Queue**: Celery (Redis broker, HTTP dispatch) — RabbitMQ removed
- **Frontend**: Vue 3 + TypeScript + Vite + Element Plus + Pinia
- **Observability**: OpenTelemetry + Sentry

## Routing Overview

| Router | Prefix | Purpose |
|--------|--------|---------|
| health_router | /api/v1 | Health check endpoint |
| auth_router | /api/v1 | JWT authentication |
| oms_router | /api/v1 | Order management (CRUD + split/merge) |
| wms_router | /api/v1 | Warehouse operations (vendors, shipments, POs, invoices) |
| barcode_router | /api/v1 | Barcode generation/validation/scanning/templates |
| logistics_router | /api/v1 | Logistics tracking |
| tms_router | /api/v1 | Transport orders, waybills, exceptions, returns |
| mobile_router | /api/v1 | Mobile-specific endpoints |
| connectors_router | /api/v1 | Connector configuration (Shopify/Amazon) |
| notification_router | — | WebSocket notifications |
| analytics_router | — | Analytics dashboard |
| admin_router | — | Admin HTML pages + user management |

## Middleware Chain

TraceContext → RequestIDMiddleware → RequestLoggingMiddleware → AuditLogMiddleware.

## Business Domains

- **OMS**: Order, OrderItem, OrderStatusLog, MergeGroup
- **WMS**: Vendor, Shipment, PurchaseOrder, Invoice, CreditMemo, WarehouseLocation
- **TMS**: TransportOrder, Waybill, ReturnOrder, TransportException, RoutePlan, FreightTier
- **Core**: OutboxEvent

## Data Flow Diagram

```
[Shopify/Amazon] → connectors_router → oms_router → WMS (shipment) → TMS (waybill) → delivery
                            ↓
                    outbox dispatch (HTTP) → consumer
```

## Deployment

docker-compose.prod.yml / Helm chart via GitHub Actions CI.
