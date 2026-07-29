"""PDA offline mode package.

Provides local SQLite storage for warehouse PDA devices, sync queue
management for eventual consistency, and API endpoints for push/pull
synchronisation.

Typical flow:
    1. PDA scans a barcode → local SQLite write + SyncQueue entry
    2. When online, ``/api/v1/sync/push`` pushes pending mutations
    3. Server validates & applies, returns success/failure per record
    4. Client marks synced records locally via ``/api/v1/sync/ack``
    5. ``/api/v1/sync/pull`` fetches server-side changes since last sync
"""
from src.pda.models import PendingMutation, SyncOperation  # noqa: F401
from src.pda.router import router  # noqa: F401
from src.pda.service import enqueue_mutation, process_pending_mutations  # noqa: F401

__all__ = [
    "PendingMutation",
    "SyncOperation",
    "enqueue_mutation",
    "process_pending_mutations",
    "router",
]

