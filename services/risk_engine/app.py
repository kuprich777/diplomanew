import hashlib
import json
import os
import random
from pathlib import Path
from statistics import mean

import requests
from flask import Flask, jsonify, request

from shared.risk_state import build_risk_state

import yaml

app = Flask(__name__)
SERVICE_NAME = "risk_engine"
SECTOR_INDEX = {"energy": 0, "water": 1, "transport": 2}
SCENARIO_DIR = Path(__file__).resolve().parents[2] / "shared" / "scenarios"
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


def _clip(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _validate_ranges(x0, matrix_a):
    if not x0:
        raise ValueError("x0 must not be empty")

    n = len(x0)
    if len(matrix_a) != n:
        raise ValueError("A must be square and match x0 dimensionality")

    for idx, value in enumerate(x0):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"x0[{idx}] must be in [0,1]")

    for i, row in enumerate(matrix_a):
        if len(row) != n:
            raise ValueError("A must be square and match x0 dimensionality")
        for j, value in enumerate(row):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"A[{i}][{j}] must be in [0,1]")


def _matrix_version(matrix_a):
    payload = json.dumps(matrix_a, separators=(",", ":"), sort_keys=False)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _matvec(matrix_a, x):
    return [sum(weight * xj for weight, xj in zip(row, x)) for row in matrix_a]


def _risk_value(state, weights):
    norm = sum(weights)
    if norm == 0:
        raise ValueError("weights sum must be > 0")
    return sum(value * weight for value, weight in zip(state, weights)) / norm


def _validate_step_schema(step):
    required = {"t", "sector", "action", "params"}
    if not isinstance(step, dict):
        raise ValueError("scenario step must be an object")
    if set(step.keys()) != required:
        raise ValueError("scenario step schema must be exactly: {t, sector, action, params}")


def _step_to_control_vector(step, size):
    _validate_step_schema(step)
    action = step["action"]
    sector = step["sector"]
    params = step["params"]
    vector = [0.0] * size

    if not isinstance(params, dict):
        raise ValueError("step params must be an object")

    magnitude = float(params.get("magnitude", 1.0))

    if action == "custom":
        control = params.get("vector")
        if not isinstance(control, list) or len(control) != size:
            raise ValueError("custom action requires params.vector with same length as state vector")
        return [float(value) for value in control]

    if action == "cascade":
        targets = params.get("targets")
        if not isinstance(targets, dict):
            raise ValueError("cascade action requires params.targets object")
        for target, impact in targets.items():
            if target not in SECTOR_INDEX:
                raise ValueError(f"unknown target sector: {target}")
            vector[SECTOR_INDEX[target]] += float(impact) * magnitude
        return vector

    action_impact = {
        "failure": 0.35,
        "load_spike": 0.25,
        "degradation": 0.20,
        "recovery": -0.20,
        "stress": 0.15,
    }
    if action not in action_impact:
        raise ValueError(f"unknown action: {action}")
    if sector not in SECTOR_INDEX:
        raise ValueError(f"unknown sector: {sector}")

    vector[SECTOR_INDEX[sector]] += action_impact[action] * magnitude
    return vector


def _scenario_controls(steps, horizon, size):
    controls = [[0.0] * size for _ in range(horizon)]
    for step in steps:
        vector = _step_to_control_vector(step, size)
        t = int(step["t"])
        if t < 0 or t >= horizon:
            raise ValueError(f"step time t={t} is out of horizon [0, {horizon - 1}]")
        controls[t] = [prev + cur for prev, cur in zip(controls[t], vector)]
    return controls


def _simulate_fq(matrix_a, x0, steps, controls=None, rng=None, noise=0.0):
    state = list(x0)
    trajectory = [state]
    controls = controls or [[0.0 for _ in state] for _ in range(steps)]

    for tick in range(steps):
        base_control = controls[tick] if tick < len(controls) else [0.0 for _ in state]
        stochastic = [rng.uniform(-noise, noise) for _ in state] if rng is not None else [0.0 for _ in state]
        influence = _matvec(matrix_a, state)
        u_t = [ctrl + rnd for ctrl, rnd in zip(base_control, stochastic)]
        state = [_clip(cur + control + infl) for cur, control, infl in zip(state, u_t, influence)]
        trajectory.append(state)
    return trajectory


def _simulate_fcl(matrix_a, x0, theta, steps):
    state = [1 if value >= theta else 0 for value in x0]
    trajectory = [state]
    for _ in range(steps):
        next_state = []
        for i, row in enumerate(matrix_a):
            propagated = any(row[j] > 0 and state[j] == 1 for j in range(len(state)))
            next_state.append(1 if state[i] == 1 or propagated else 0)
        state = next_state
        trajectory.append(state)
    return trajectory


def _average_risk(trajectory, weights):
    return mean(_risk_value(state, weights) for state in trajectory)


def _run_once(matrix_a, x0, theta, steps, weights, controls=None, rng=None, noise=0.0):
    fq = _simulate_fq(matrix_a=matrix_a, x0=x0, steps=steps, controls=controls, rng=rng, noise=noise)
    fcl = _simulate_fcl(matrix_a=matrix_a, x0=x0, theta=theta, steps=steps)
    return {
        "fq": fq,
        "fcl": fcl,
        "Iq": _average_risk(fq, weights),
        "Icl": _average_risk(fcl, weights),
    }


def _load_scenario_file(path):
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"unsupported scenario format: {path.name}")

    if not isinstance(data, dict):
        raise ValueError("scenario file must contain an object")
    scenario_id = data.get("id") or path.stem
    steps = data.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("scenario steps must be a list")
    for step in steps:
        _validate_step_schema(step)

    return {
        "id": scenario_id,
        "name": data.get("name", scenario_id),
        "description": data.get("description", ""),
        "steps": steps,
        "source": str(path.relative_to(Path(__file__).resolve().parents[2])),
    }


def _load_scenarios():
    if not SCENARIO_DIR.exists():
        return []

    items = []
    for path in sorted(SCENARIO_DIR.iterdir()):
        if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
            continue
        items.append(_load_scenario_file(path))
    return items


def _find_scenario(scenario_id):
    for scenario in _load_scenarios():
        if scenario["id"] == scenario_id:
            return scenario
    raise ValueError(f"scenario not found: {scenario_id}")


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME})


@app.get("/api/v1/risk/scenarios")
def list_scenarios():
    scenarios = _load_scenarios()
    response = [
        {
            "id": item["id"],
            "name": item["name"],
            "description": item["description"],
            "step_count": len(item["steps"]),
            "source": item["source"],
        }
        for item in scenarios
    ]
    return jsonify(response)


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


@app.post("/api/v1/risk/run")
def run_scenario():
    payload = request.get_json(silent=True) or {}

    required = ["scenario_id", "run_id", "mode", "A", "x0", "theta", "delta", "weights"]
    missing = [field for field in required if field not in payload]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    scenario_id = payload["scenario_id"]
    run_id = payload["run_id"]
    mode = payload["mode"]
    matrix_a = payload["A"]
    x0 = payload["x0"]
    theta = float(payload["theta"])
    steps = int(payload["delta"])
    weights = payload["weights"]
    seed = payload.get("seed")
    scenario_steps = payload.get("scenario_steps")

    if mode not in {"q", "cl", "monte_carlo_q", "monte_carlo_cl"}:
        return jsonify({"error": "mode must be one of: q, cl, monte_carlo_q, monte_carlo_cl"}), 400

    if not 0.0 <= theta <= 1.0:
        return jsonify({"error": "theta must be in [0,1]"}), 400
    if steps < 1:
        return jsonify({"error": "delta must be >= 1"}), 400
    if not isinstance(weights, list) or len(weights) != len(x0):
        return jsonify({"error": "weights must be a list with same length as x0"}), 400

    try:
        _validate_ranges(x0, matrix_a)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        weights = [float(weight) for weight in weights]
        if any(weight < 0 for weight in weights):
            return jsonify({"error": "weights must be non-negative"}), 400
        _risk_value(x0, weights)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid weights: {exc}"}), 400

    if scenario_steps is None:
        scenario_steps = []

    try:
        controls = _scenario_controls(scenario_steps, horizon=steps, size=len(x0))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid scenario_steps: {exc}"}), 400

    a_version = _matrix_version(matrix_a)
    runs = int(payload.get("runs", 100))
    noise = float(payload.get("noise", 0.05))

    if mode.startswith("monte_carlo"):
        if seed is None:
            seed = int(os.getenv("RISK_SEED", "42"))
        rng = random.Random(int(seed))
        simulations = [
            _run_once(matrix_a, x0, theta, steps, weights, controls=controls, rng=rng, noise=noise)
            for _ in range(runs)
        ]
        iq = mean(sim["Iq"] for sim in simulations)
        icl = mean(sim["Icl"] for sim in simulations)
        chosen_key = "fq" if mode.endswith("_q") else "fcl"
        trajectory = simulations[-1][chosen_key]
    else:
        result = _run_once(matrix_a, x0, theta, steps, weights, controls=controls)
        iq = result["Iq"]
        icl = result["Icl"]
        trajectory = result["fq" if mode == "q" else "fcl"]

    r0 = _risk_value(trajectory[0], weights)
    rt = _risk_value(trajectory[-1], weights)

    return jsonify(
        {
            "scenario_id": scenario_id,
            "run_id": run_id,
            "mode": mode,
            "matrix_A_version": a_version,
            "seed": seed,
            "controls": controls,
            "trajectory": trajectory,
            "R0": r0,
            "RT": rt,
            "delta_R": rt - r0,
            "Iq": iq,
            "Icl": icl,
        }
    )


@app.post("/api/v1/risk/scenarios/<scenario_id>/monte-carlo")
def run_scenario_batch(scenario_id):
    payload = request.get_json(silent=True) or {}
    try:
        scenario = _find_scenario(scenario_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    payload.update(
        {
            "scenario_id": scenario_id,
            "run_id": payload.get("run_id", f"batch-{scenario_id}"),
            "mode": payload.get("mode", "monte_carlo_q"),
            "scenario_steps": scenario["steps"],
        }
    )

    with app.test_request_context("/api/v1/risk/run", method="POST", json=payload):
        return run_scenario()


@app.get("/api/v1/risk/state")
def state():
    return jsonify(LAST_STATE)


@app.errorhandler(requests.RequestException)
def handle_upstream_error(err):
    return jsonify({"error": str(err), "service": SERVICE_NAME}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8004")))
