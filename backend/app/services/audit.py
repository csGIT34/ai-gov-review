"""Append-only audit writer.

Every state change routes through `record()`. Rows are never updated/deleted
(a Postgres trigger enforces this in prod; app code never mutates them).
An optional hash chain makes tampering detectable.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog


def _hash(prev: str | None, payload: dict) -> str:
    h = hashlib.sha256()
    h.update((prev or "").encode())
    h.update(json.dumps(payload, sort_keys=True, default=str).encode())
    return h.hexdigest()


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    actor_type: str = "user",
    before: dict | None = None,
    after: dict | None = None,
    request_ip: str | None = None,
) -> AuditLog:
    # Deterministic predecessor for the hash chain: newest ts, then id as a stable
    # tiebreak so same-timestamp rows don't produce a nondeterministic prev.
    # (Full concurrency-safety would require a monotonic sequence + row lock.)
    prev = db.execute(
        select(AuditLog.hash_self).order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(1)
    ).scalar_one_or_none()

    payload = {
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "actor_id": str(actor_id) if actor_id else None,
        "actor_type": actor_type,
        "before": before,
        "after": after,
    }
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        actor_type=actor_type,
        before=before,
        after=after,
        request_ip=request_ip,
        hash_prev=prev,
        hash_self=_hash(prev, payload),
    )
    db.add(entry)
    db.flush()
    return entry
