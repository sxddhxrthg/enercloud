"""
ENERCloud sensor simulator (SIMULATED smart energy meters).

Uses only the Python standard library - no pip install needed.

Modes:
  stream  - every sensor sends a normal reading every --interval seconds
  spike   - one building sends an abnormal reading
  load    - performance test: N requests with C concurrent senders

--dry-run: nothing is sent to AWS. Readings are passed through the SAME
           processing.py logic used by the Lambda, so anomaly detection can
           be tested locally.

Cloud mode needs two environment variables:
  ENERCLOUD_API_URL   e.g. https://abc123.execute-api.ap-south-1.amazonaws.com/prod
  ENERCLOUD_API_KEY   API Gateway API key
"""
import argparse
import csv
import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lambda", "ingest"))
from processing import BUILDINGS, process_reading  # noqa: E402

local_history = {b: [] for b in BUILDINGS}   # dry-run only: newest-first normal readings


# ---------------------------------------------------------------- readings
def make_reading(building_id, spike=False):
    cfg = BUILDINGS[building_id]
    if spike:
        target_kw = cfg["max_kw"] * random.uniform(1.3, 1.6)
    else:
        # Normal load fluctuates +/-15% around the middle of the building's band
        mid = (cfg["normal_min_kw"] + cfg["normal_max_kw"]) / 2
        target_kw = mid * random.uniform(0.85, 1.15)
    voltage = round(min(max(random.gauss(230, 3), 215), 245), 1)
    current = round(target_kw * 1000 / voltage, 2)
    return {
        "building_id": building_id,
        "sensor_id": cfg["sensor_id"],
        "voltage": voltage,
        "current": current,
        "sensor_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- senders
def send_local(reading):
    """Dry run: process locally with the shared anomaly logic."""
    start = time.perf_counter()
    record, errors = process_reading(reading, local_history[reading["building_id"]])
    ms = (time.perf_counter() - start) * 1000
    if errors:
        return 400, {"errors": errors}, ms
    if record["status"] == "NORMAL":
        local_history[record["building_id"]].insert(0, record["power_kw"])
    return 200, record, ms


def send_cloud(reading, url, api_key, timeout=15):
    body = json.dumps(reading).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/readings", data=body, method="POST",
        headers={"Content-Type": "application/json", "x-api-key": api_key})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, text = resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode()
    except Exception as e:  # network error, timeout
        status, text = 0, json.dumps({"error": str(e)})
    ms = (time.perf_counter() - start) * 1000
    try:
        data = json.loads(text)
    except ValueError:
        data = {"raw": text}
    return status, data, ms


def build_sender(args):
    if args.dry_run:
        return send_local
    url, key = os.environ.get("ENERCLOUD_API_URL"), os.environ.get("ENERCLOUD_API_KEY")
    if not url or not key:
        sys.exit("Set ENERCLOUD_API_URL and ENERCLOUD_API_KEY, or use --dry-run")
    return lambda r: send_cloud(r, url, key)


def describe(status, data, ms):
    if status == 200:
        rec = data.get("reading", data)
        line = f"{rec.get('building_id'):9} {rec.get('power_kw'):>7} kW  {rec.get('status'):7}"
        if rec.get("reasons"):
            line += "  <- " + "; ".join(rec["reasons"])
    else:
        line = f"HTTP {status}: {data}"
    return f"{line}   ({ms:.1f} ms)"


# ---------------------------------------------------------------- modes
def run_stream(args, send):
    mode = "DRY RUN (local)" if args.dry_run else "CLOUD"
    print(f"Streaming [{mode}] - {len(BUILDINGS)} sensors, every {args.interval}s. Ctrl+C to stop.")
    rounds = 0
    try:
        while args.rounds == 0 or rounds < args.rounds:
            rounds += 1
            print(f"\n--- round {rounds} ---")
            for b in BUILDINGS:
                print(describe(*send(make_reading(b))))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def run_spike(args, send):
    if args.dry_run:  # build up a local baseline first so both rules can be shown
        for _ in range(6):
            send(make_reading(args.building))
    print(f"Sending ABNORMAL reading for {args.building}:")
    print(describe(*send(make_reading(args.building, spike=True))))


def run_load(args, send):
    buildings = list(BUILDINGS)
    readings = [make_reading(buildings[i % len(buildings)]) for i in range(args.requests)]
    print(f"Load test: {args.requests} requests, concurrency {args.concurrency}, "
          f"{'DRY RUN' if args.dry_run else 'CLOUD'}")
    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(send, readings))
    wall_s = time.perf_counter() - wall_start

    latencies = [ms for _, _, ms in results]
    ok = sum(1 for s, _, _ in results if s == 200)
    codes = {}
    for s, _, _ in results:
        codes[s] = codes.get(s, 0) + 1
    lat_sorted = sorted(latencies)
    p95 = lat_sorted[max(0, int(round(0.95 * len(lat_sorted))) - 1)]

    summary = {
        "mode": "dry-run" if args.dry_run else "cloud",
        "requests": args.requests, "concurrency": args.concurrency,
        "success": ok, "failed": args.requests - ok,
        "success_rate_pct": round(100 * ok / args.requests, 2),
        "status_codes": codes,
        "avg_ms": round(statistics.mean(latencies), 1),
        "p50_ms": round(statistics.median(latencies), 1),
        "p95_ms": round(p95, 1),
        "max_ms": round(max(latencies), 1),
        "wall_time_s": round(wall_s, 2),
        "throughput_rps": round(args.requests / wall_s, 2),
    }
    print(json.dumps(summary, indent=2))

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["building_id", "status_code", "latency_ms"])
            for r, (s, _, ms) in zip(readings, results):
                w.writerow([r["building_id"], s, round(ms, 2)])
        with open(args.out.replace(".csv", "_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)
        print(f"Saved per-request results to {args.out}")


# ---------------------------------------------------------------- CLI
def main():
    p = argparse.ArgumentParser(description="ENERCloud sensor simulator")
    p.add_argument("--dry-run", action="store_true", help="process locally, send nothing")
    sub = p.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("stream")
    s.add_argument("--interval", type=float, default=3)
    s.add_argument("--rounds", type=int, default=0, help="0 = run until Ctrl+C")

    sp = sub.add_parser("spike")
    sp.add_argument("--building", choices=list(BUILDINGS), default="LAB-1")

    ld = sub.add_parser("load")
    ld.add_argument("--requests", type=int, default=10)
    ld.add_argument("--concurrency", type=int, default=5)
    ld.add_argument("--out", help="CSV path for per-request results")

    args = p.parse_args()
    send = build_sender(args)
    {"stream": run_stream, "spike": run_spike, "load": run_load}[args.mode](args, send)


if __name__ == "__main__":
    main()
