"""Safe sending evidence from a QBO Estimate; no inferred send dates."""
from datetime import datetime


def estimate_send_evidence(estimate: dict) -> dict[str, str]:
    email_status = str(estimate.get("EmailStatus") or "").strip()
    sent = email_status == "EmailSent"
    delivery = estimate.get("DeliveryInfo")
    sent_at = ""
    if sent and isinstance(delivery, dict):
        value = str(delivery.get("DeliveryTime") or "").strip()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                sent_at = value
        except ValueError:
            pass
    return {
        "qbo_estimate_sent_status": "sent" if sent else "not_confirmed" if email_status in {"NotSet", "NeedToSend"} else "",
        "qbo_estimate_sent_at": sent_at,
    }


def merge_send_evidence(current, estimate_id: str, status: str, sent_at: str) -> tuple[str, str]:
    """Sending is a historical milestone scoped to one Estimate ID."""
    if estimate_id and estimate_id == current.qbo_estimate_id:
        if current.qbo_estimate_sent_status == "sent":
            status = "sent"
        status = status or current.qbo_estimate_sent_status
        sent_at = sent_at or current.qbo_estimate_sent_at
    return status, sent_at if status == "sent" else ""
