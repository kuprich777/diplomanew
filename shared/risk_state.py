from datetime import datetime, timezone
from typing import Any, Dict, List


def build_risk_state(
    service: str,
    level: str,
    score: float,
    summary: str,
    signals: List[Dict[str, Any]],
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "service": service,
        "risk": {
            "level": level,
            "score": round(score, 4),
            "summary": summary,
            "signals": signals,
        },
        "metadata": metadata or {},
    }
