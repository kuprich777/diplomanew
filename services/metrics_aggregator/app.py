import os

import requests
from flask import Flask, jsonify

app = Flask(__name__)
SERVICE_NAME = "metrics_aggregator"


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME})


@app.get("/api/v1/metrics/summary")
def summary():
    timeout = float(os.getenv("REQUEST_TIMEOUT_SEC", "2"))
    risk_state = requests.get(f"{os.getenv('RISK_ENGINE_URL')}/api/v1/risk/state", timeout=timeout)
    risk_state.raise_for_status()
    payload = risk_state.json()

    return jsonify(
        {
            "service": SERVICE_NAME,
            "risk_level": payload["risk"]["level"],
            "risk_score": payload["risk"]["score"],
            "source_service": payload["service"],
            "timestamp_utc": payload["timestamp_utc"],
            "signals_count": len(payload["risk"]["signals"]),
        }
    )


@app.errorhandler(requests.RequestException)
def handle_upstream_error(err):
    return jsonify({"error": str(err), "service": SERVICE_NAME}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8005")))
