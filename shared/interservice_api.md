# Межсервисное взаимодействие (REST JSON)

Все сервисы используют HTTP + JSON и общую схему сообщения состояния риска.

## Базовые правила

- `GET /health` — liveness/readiness endpoint для каждого сервиса.
- Все доменные endpoint'ы находятся под префиксом `/api/v1/...`.
- Таймаут межсервисных вызовов задаётся переменной `REQUEST_TIMEOUT_SEC`.
- Ошибки возвращаются в формате:

```json
{
  "error": "message",
  "service": "service_name"
}
```

## Сервисы и endpoint'ы

### energy
- `GET /api/v1/energy/demand`
- `GET /api/v1/energy/supply`

### water
- `GET /api/v1/water/quality`
- `GET /api/v1/water/reservoir`

### transport
- `GET /api/v1/transport/load`
- `GET /api/v1/transport/incidents`

### risk_engine
- `POST /api/v1/risk/evaluate`
  - Запускает Monte Carlo (число прогонов задаётся `MONTE_CARLO_RUNS`)
  - Ходит в `energy`, `water`, `transport` за входными сигналами.
- `GET /api/v1/risk/state`
  - Возвращает последнее рассчитанное состояние риска.

### metrics_aggregator
- `GET /api/v1/metrics/summary`
  - Получает данные из `risk_engine` и строит итоговую сводку для внешних клиентов.

## Единый формат сообщения состояния риска

```json
{
  "schema_version": "1.0",
  "timestamp_utc": "2026-01-01T12:00:00+00:00",
  "service": "risk_engine",
  "risk": {
    "level": "low|medium|high|critical",
    "score": 0.42,
    "summary": "text summary",
    "signals": [
      {
        "name": "energy_demand",
        "value": 78.2,
        "weight": 0.35
      }
    ]
  },
  "metadata": {
    "seed": 42,
    "runs": 2000
  }
}
```
