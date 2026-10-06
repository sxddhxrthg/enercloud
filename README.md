# ENERCloud

**A Serverless Cloud Platform for Real-Time Campus Energy Monitoring and Anomaly Detection**
21CSE362T Cloud Computing, FT-III project.

> Status: Phase 1 (local foundation) complete. AWS deployment in progress.
> The sensors are a **simulation**; the cloud backend is real AWS infrastructure.

## Architecture
Sensor Simulator -> API Gateway (REST, API key) -> Lambda (ingest: validate, compute kW, detect anomaly)
-> DynamoDB -> Lambda (dashboard/export) -> Dashboard, with S3 (reports), SNS (alerts),
CloudWatch (logs/metrics) and IAM (least-privilege roles). Region: ap-south-1.

## Project structure
```
frontend/         dashboard (HTML/CSS/JS; mock mode until the API is connected)
simulator/        Python sensor simulator (standard library only)
lambda/ingest/    processing.py (validation + anomaly rules); Lambda handler added in Phase 3
lambda/dashboard/ dashboard + export Lambda (Phase 3)
tests/            unit tests
docs/             API contract, report material
results/          load-test outputs (actual measurements only)
architecture/     diagrams
```

## Run locally
```bash
python3 -m unittest discover -s tests -v                       # from project root
cd simulator && python3 simulator.py --dry-run stream --rounds 3 --interval 1
python3 simulator.py --dry-run spike --building LAB-1
cd ../frontend && python3 -m http.server 8000                  # open http://localhost:8000
```

## Anomaly detection
1. **Threshold rule**: power above the building's configured limit.
2. **Baseline deviation rule**: power more than 1.5x the average of the last 10 normal readings
   (needs at least 5). Anomalous readings are excluded from the baseline.
