# Diploma microservices scaffold

## Запуск

```bash
cp .env.example .env
docker compose up --build
```

## Проверка

- `GET http://localhost:8001/health`
- `POST http://localhost:8004/api/v1/risk/evaluate`
- `GET http://localhost:8005/api/v1/metrics/summary`

Детали контрактов: `shared/interservice_api.md`.
