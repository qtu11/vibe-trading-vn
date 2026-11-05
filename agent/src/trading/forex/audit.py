"""Fan live forex outcomes into the existing redacted, hash-chained ledger."""

from src.live.audit import LiveActionEvent, write_live_action


def record_outcome(config, row, state, result, mandate=None, *, gate_allowed=True):
    if config.environment != "live":
        return None
    consent = mandate.consent if mandate else None
    outcome = (
        "filled"
        if state == "filled"
        else "rejected"
        if state in ("rejected", "cancelled")
        else "error"
        if state == "unknown"
        else "accepted"
    )
    if not gate_allowed:
        outcome = "blocked"
    return write_live_action(
        LiveActionEvent(
            kind="order_rejected" if state in ("rejected", "cancelled") else "order_placed",
            session_id=row["id"],
            server=config.mandate_key,
            remote_tool="forex_submit_intent",
            outcome=outcome,
            mandate_snapshot_ref=consent.consent_token_sha256 if consent else None,
            consent_record_ref=consent.account_ref if consent else None,
            intent_normalized=f"{row['payload']['side']} {row['payload']['quantity']} {row['payload']['symbol']} @ market",
            broker_request={"intent_id": row["id"], "connector": config.connector, "order": row["payload"]},
            broker_response=result,
            gate_decision={
                "allowed": gate_allowed,
                "binding_hash": row["binding_hash"],
                "failure_code": result.get("code"),
                "checked_limits": [
                    "identity",
                    "quote",
                    "volume",
                    "stop_risk",
                    "margin",
                    "exposure",
                    "leverage",
                    "daily",
                    "drawdown",
                    "mandate",
                    "halt",
                ]
                if gate_allowed
                else ["preflight"],
            },
        ),
        require_durable=True,
    )
