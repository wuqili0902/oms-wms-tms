"""ERP/EDI Connectors package.

Translates between internal models and external enterprise / marketplace
formats (SAP IDOC, EDI X12, Shopify webhooks, Amazon SP-API).

Each connector module exposes:
  - ``parse(raw: str) -> ERPMessage`` — convert external format → internal
  - ``serialize(msg: ERPMessage) -> str`` — convert internal → external format

See ``src.models.erp_connector`` for the shared message model and connector
base classes.
"""
from src.models.erp_connector import (
    ERPMessage,
    MessageType,
    OracleEDIConnector,
    OrderSyncService,
    SAPPIConnector,
)

__all__ = [
    "ERPMessage",
    "MessageType",
    "SAPPIConnector",
    "OracleEDIConnector",
    "OrderSyncService",
]
