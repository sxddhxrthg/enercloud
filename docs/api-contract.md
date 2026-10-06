# ENERCloud API contract

Base URL: `https://<api-id>.execute-api.ap-south-1.amazonaws.com/prod`
All requests use HTTPS and the header `x-api-key: <key>`.

## POST /readings  (sensor -> cloud)
Request body:
```json
{"building_id": "LAB-1", "sensor_id": "SEN-LAB-1-01", "voltage": 230.1, "current": 13.2, "sensor_ts": "2026-10-05T10:32:10+00:00"}
```
- `power_kw` is calculated on the server (V x I / 1000, power factor assumed 1.0).
- `200` -> `{"message": "stored", "reading": {...stored record...}}`
- `400` -> `{"errors": ["..."]}` (validation failure, nothing stored)

## GET /dashboard  (dashboard -> cloud)
```json
{
  "generated_at": "ISO-8601",
  "summary": {"total_buildings": 5, "active_sensors": 5, "total_power_kw": 23.8,
              "anomaly_count": 1, "readings_count": 30},
  "buildings": [{"building_id": "LAB-1", "name": "Computer Lab 1", "type": "Laboratory",
                 "sensor_id": "SEN-LAB-1-01", "normal_min_kw": 2.0, "normal_max_kw": 4.0,
                 "max_kw": 6.0, "latest": "reading object or null"}],
  "recent_readings": ["reading objects, newest first"],
  "anomalies": ["reading objects with status ANOMALY"]
}
```
Reading record: `building_id, sensor_id, ts, voltage, current, power_kw, status (NORMAL|ANOMALY), reasons[], baseline_kw`

## POST /export  (dashboard -> cloud -> S3)
`200` -> `{"bucket": "...", "json_key": "reports/....json", "csv_key": "reports/....csv", "records": 30}`

## Anomaly rules (lambda/ingest/processing.py)
1. THRESHOLD: power_kw > building max_kw
2. DEVIATION: at least 5 previous NORMAL readings exist and power_kw > 1.5 x their average (last 10)
