import os
from flask import Flask, jsonify

app = Flask(__name__)
SERVICE_NAME = "transport"


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME})


@app.get("/api/v1/transport/load")
def load():
    value = float(os.getenv("TRANSPORT_LOAD", "0.67"))
    return jsonify({"service": SERVICE_NAME, "metric": "load_factor", "value": value, "unit": "ratio"})


@app.get("/api/v1/transport/incidents")
def incidents():
    value = int(os.getenv("TRANSPORT_INCIDENTS", "4"))
    return jsonify({"service": SERVICE_NAME, "metric": "incidents_per_day", "value": value, "unit": "count"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8003")))
