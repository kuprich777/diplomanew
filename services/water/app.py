import os
from flask import Flask, jsonify

app = Flask(__name__)
SERVICE_NAME = "water"


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME})


@app.get("/api/v1/water/quality")
def quality():
    value = float(os.getenv("WATER_QUALITY_INDEX", "88.0"))
    return jsonify({"service": SERVICE_NAME, "metric": "quality_index", "value": value, "unit": "WQI"})


@app.get("/api/v1/water/reservoir")
def reservoir():
    value = float(os.getenv("WATER_RESERVOIR_LEVEL", "63.5"))
    return jsonify({"service": SERVICE_NAME, "metric": "reservoir_level", "value": value, "unit": "%"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8002")))
