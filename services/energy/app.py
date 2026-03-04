import os
from flask import Flask, jsonify

app = Flask(__name__)
SERVICE_NAME = "energy"


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME})


@app.get("/api/v1/energy/demand")
def demand():
    base = float(os.getenv("ENERGY_BASE_DEMAND", "72.5"))
    return jsonify({"service": SERVICE_NAME, "metric": "demand", "value": base, "unit": "MW"})


@app.get("/api/v1/energy/supply")
def supply():
    base = float(os.getenv("ENERGY_BASE_SUPPLY", "81.0"))
    return jsonify({"service": SERVICE_NAME, "metric": "supply", "value": base, "unit": "MW"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8001")))
