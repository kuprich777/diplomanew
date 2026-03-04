import os
import random
from statistics import mean

import requests
from flask import Flask, jsonify, request

from shared.risk_state import build_risk_state

app = Flask(__name__)
SERVICE_NAME = "risk_engine"
LAST_STATE = build_risk_state(
    service=SERVICE_NAME,
    level="low",
    score=0.0,
    summary="No evaluation has been run yet.",
    signals=[],
    metadata={"seed": None, "runs": 0},
)


def _safe_get(url: str, timeout: float):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _level_from_score(score: float) -> str:
    if score < 0.25:
        return "low"
    if score < 0.5:
        return "medium"
    if score < 0.75:
        return "high"
    return "critical"


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME})


@app.post("/api/v1/risk/evaluate")
def evaluate():
    global LAST_STATE

    timeout = float(os.getenv("REQUEST_TIMEOUT_SEC", "2"))
    seed = int(os.getenv("RISK_SEED", "42"))
    runs = int(os.getenv("MONTE_CARLO_RUNS", "1000"))
    rng = random.Random(seed)

    energy = _safe_get(f"{os.getenv('ENERGY_URL')}/api/v1/energy/demand", timeout)
    water = _safe_get(f"{os.getenv('WATER_URL')}/api/v1/water/reservoir", timeout)
    transport = _safe_get(f"{os.getenv('TRANSPORT_URL')}/api/v1/transport/load", timeout)

    base_score = (
        min(energy["value"] / 100.0, 1.0) * 0.45
        + (1.0 - min(water["value"] / 100.0, 1.0)) * 0.30
        + min(transport["value"], 1.0) * 0.25
    )

    samples = [min(max(base_score + rng.uniform(-0.1, 0.1), 0.0), 1.0) for _ in range(runs)]
    score = mean(samples)
    level = _level_from_score(score)

    signals = [
        {"name": "energy_demand", "value": energy["value"], "weight": 0.45},
        {"name": "water_reservoir_inverse", "value": 1.0 - water["value"] / 100.0, "weight": 0.30},
        {"name": "transport_load", "value": transport["value"], "weight": 0.25},
    ]

    LAST_STATE = build_risk_state(
        service=SERVICE_NAME,
        level=level,
        score=score,
        summary=f"Risk evaluated with Monte Carlo ({runs} runs)",
        signals=signals,
        metadata={"seed": seed, "runs": runs},
    )
    return jsonify(LAST_STATE)


@app.get("/api/v1/risk/state")
def state():
    return jsonify(LAST_STATE)


@app.errorhandler(requests.RequestException)
def handle_upstream_error(err):
    return jsonify({"error": str(err), "service": SERVICE_NAME}), 502


@app.errorhandler(Exception)
def handle_generic(err):
    return jsonify({"error": str(err), "service": SERVICE_NAME}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8004")))
