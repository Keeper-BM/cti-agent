from backend.models.tables import AuditEvent


def audit(
    db, action, *, asset_id=None, target_id=None, outcome="SUCCESS", details=None, actor_id=None
):
    """Only explicit domain fields belong in details; never request bodies or credentials."""
    principal = db.info.get("principal")
    db.add(
        AuditEvent(
            action=action,
            asset_id=str(asset_id) if asset_id else None,
            target_id=str(target_id) if target_id else None,
            outcome=outcome,
            actor_id=actor_id or (principal.user_id if principal else None),
            request_id=db.info.get("request_id"),
            details=details or {},
        )
    )
