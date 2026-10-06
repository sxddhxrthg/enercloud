"""
ENERCloud - single Lambda function behind API Gateway (Lambda proxy integration).

Routes:
  POST /readings   sensor reading -> validate -> compute kW -> anomaly rules -> DynamoDB
  GET  /dashboard  latest readings, anomalies and summary for the dashboard
  POST /export     write a JSON + CSV report of recent readings to S3

Validation and anomaly logic live in processing.py (unit-tested locally).
Configuration comes from environment variables: TABLE_NAME, BUCKET_NAME.
"""
import csv
import io
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from processing import BUILDINGS, process_reading, validate_reading

TABLE_NAME = os.environ.get("TABLE_NAME", "EnerCloudReadings")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "")

table = boto3.resource("dynamodb").Table(TABLE_NAME)
s3 = boto3.client("s3")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,x-api-key",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def respond(status, body):
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps(body)}


# ------------------------------------------------------------------ helpers
def to_plain(item):
    """DynamoDB item -> JSON-friendly reading. Also normalises older test items."""
    def num(key):
        return float(item[key]) if item.get(key) is not None else None

    status = item.get("status") or ("ANOMALY" if item.get("anomaly") else "NORMAL")
    reasons = item.get("reasons")
    if reasons is None:
        reasons = [item["anomaly_reason"]] if item.get("anomaly_reason") else []
    return {
        "building_id": item["building_id"],
        "sensor_id": item.get("sensor_id"),
        "ts": item.get("received_at") or item["ts"],
        "voltage": num("voltage"),
        "current": num("current"),
        "power_kw": num("power_kw"),
        "status": status,
        "reasons": list(reasons),
        "baseline_kw": num("baseline_kw"),
    }


def recent_readings(building_id, limit):
    """Newest-first readings for one building (partition key + sort key query)."""
    result = table.query(
        KeyConditionExpression=Key("building_id").eq(building_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [to_plain(i) for i in result.get("Items", [])]


# ------------------------------------------------------------------ routes
def handle_ingest(event):
    try:
        payload = json.loads(event.get("body") or "")
    except (TypeError, ValueError):
        return respond(400, {"errors": ["Body must be valid JSON"]})

    _, errors = validate_reading(payload)
    if errors:
        print(json.dumps({"event": "rejected", "errors": errors}))
        return respond(400, {"errors": errors})

    history = [r["power_kw"] for r in recent_readings(payload["building_id"], 10)
               if r["status"] == "NORMAL"]
    record, _ = process_reading(payload, history)

    # Server-side timestamp; random suffix prevents two readings in the same
    # millisecond from overwriting each other (same partition + sort key).
    received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    item = {
        "building_id": record["building_id"],
        "ts": f"{received_at}#{uuid.uuid4().hex[:6]}",
        "received_at": received_at,
        "sensor_id": record["sensor_id"],
        "voltage": Decimal(str(record["voltage"])),
        "current": Decimal(str(record["current"])),
        "power_kw": Decimal(str(record["power_kw"])),
        "status": record["status"],
        "reasons": record["reasons"],
    }
    if record["baseline_kw"] is not None:
        item["baseline_kw"] = Decimal(str(record["baseline_kw"]))
    if record.get("sensor_ts"):
        item["sensor_ts"] = record["sensor_ts"]

    table.put_item(Item=item)

    log = {"event": "reading", "building_id": item["building_id"],
           "power_kw": record["power_kw"], "status": record["status"]}
    if record["status"] == "ANOMALY":
        log["reasons"] = record["reasons"]
        print("ANOMALY DETECTED " + json.dumps(log))
    else:
        print(json.dumps(log))

    return respond(200, {"message": "stored", "reading": to_plain(item)})


def handle_dashboard():
    buildings, all_readings = [], []
    for building_id, cfg in BUILDINGS.items():
        readings = recent_readings(building_id, 50)
        all_readings.extend(readings)
        buildings.append({"building_id": building_id, **cfg,
                          "latest": readings[0] if readings else None})

    all_readings.sort(key=lambda r: r["ts"], reverse=True)
    anomalies = [r for r in all_readings if r["status"] == "ANOMALY"]
    total_kw = sum(b["latest"]["power_kw"] for b in buildings if b["latest"])

    return respond(200, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "total_buildings": len(buildings),
            "active_sensors": sum(1 for b in buildings if b["latest"]),
            "total_power_kw": round(total_kw, 3),
            "anomaly_count": len(anomalies),
            "readings_count": len(all_readings),
        },
        "buildings": buildings,
        "recent_readings": all_readings[:20],
        "anomalies": anomalies[:20],
    })


def handle_export():
    if not BUCKET_NAME:
        return respond(500, {"error": "BUCKET_NAME environment variable is not set"})

    rows = []
    for building_id in BUILDINGS:
        rows.extend(recent_readings(building_id, 200))
    rows.sort(key=lambda r: r["ts"])

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"reports/{stamp[:8]}/enercloud-report-{stamp}"

    buf = io.StringIO()
    fields = ["ts", "building_id", "sensor_id", "voltage", "current", "power_kw", "status", "reasons"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({**r, "reasons": "; ".join(r["reasons"])})

    s3.put_object(Bucket=BUCKET_NAME, Key=base + ".json",
                  Body=json.dumps({"generated_at": stamp, "records": rows}, indent=2),
                  ContentType="application/json")
    s3.put_object(Bucket=BUCKET_NAME, Key=base + ".csv",
                  Body=buf.getvalue(), ContentType="text/csv")

    print(json.dumps({"event": "export", "records": len(rows), "key": base}))
    return respond(200, {"bucket": BUCKET_NAME, "json_key": base + ".json",
                         "csv_key": base + ".csv", "records": len(rows)})


# ------------------------------------------------------------------ entry point
def lambda_handler(event, context):
    method = event.get("httpMethod")
    route = event.get("resource")

    try:
        if method == "OPTIONS":
            return respond(200, {"message": "ok"})
        if method == "POST" and route == "/readings":
            return handle_ingest(event)
        if method == "GET" and route == "/dashboard":
            return handle_dashboard()
        if method == "POST" and route == "/export":
            return handle_export()
        return respond(404, {"error": f"No route for {method} {route}"})
    except Exception as exc:  # logged to CloudWatch, generic message to client
        print(json.dumps({"event": "error", "route": route, "error": repr(exc)}))
        return respond(500, {"error": "Internal server error"})
