"""
ENERCloud - reading processing logic.

Pure Python (no AWS imports) so it can be unit-tested locally and reused
unchanged inside the ingest Lambda.

Responsibilities:
  1. Building / sensor configuration
  2. Input validation
  3. Server-side power calculation
  4. Anomaly detection (two explainable rules)
"""

# --------------------------------------------------------------------------
# 1. Configuration
#    normal_min_kw / normal_max_kw : expected consumption band (used by the
#                                    simulator and shown on the dashboard)
#    max_kw                        : hard threshold for Rule 1
# --------------------------------------------------------------------------
BUILDINGS = {
    "ACAD-A":   {"name": "Academic Block A", "type": "Classrooms",
                 "sensor_id": "SEN-ACAD-A-01",   "normal_min_kw": 3.0, "normal_max_kw": 6.0, "max_kw": 9.0},
    "LAB-1":    {"name": "Computer Lab 1",   "type": "Laboratory",
                 "sensor_id": "SEN-LAB-1-01",    "normal_min_kw": 2.0, "normal_max_kw": 4.0, "max_kw": 6.0},
    "LIB":      {"name": "Central Library",  "type": "Library",
                 "sensor_id": "SEN-LIB-01",      "normal_min_kw": 1.5, "normal_max_kw": 3.0, "max_kw": 5.0},
    "HOSTEL-A": {"name": "Hostel A",         "type": "Hostel",
                 "sensor_id": "SEN-HOSTEL-A-01", "normal_min_kw": 4.0, "normal_max_kw": 8.0, "max_kw": 12.0},
    "ADMIN":    {"name": "Admin Block",      "type": "Administration",
                 "sensor_id": "SEN-ADMIN-01",    "normal_min_kw": 1.0, "normal_max_kw": 2.5, "max_kw": 4.0},
}

VOLTAGE_MIN, VOLTAGE_MAX = 180.0, 260.0   # Indian mains nominal 230 V
CURRENT_MIN, CURRENT_MAX = 0.0, 200.0     # amperes

BASELINE_WINDOW = 10        # use up to the last 10 normal readings
BASELINE_MIN_SAMPLES = 5    # Rule 2 only applies once we have 5 readings
DEVIATION_FACTOR = 1.5      # flag if power > 1.5 x baseline (i.e. +50%)


# --------------------------------------------------------------------------
# 2. Validation
# --------------------------------------------------------------------------
def _is_number(value):
    # bool is a subclass of int in Python, so exclude it explicitly
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_reading(payload):
    """Return (clean_reading, errors). clean_reading is None if invalid."""
    errors = []

    if not isinstance(payload, dict):
        return None, ["Body must be a JSON object"]

    building_id = payload.get("building_id")
    sensor_id = payload.get("sensor_id")
    voltage = payload.get("voltage")
    current = payload.get("current")

    if building_id not in BUILDINGS:
        errors.append(f"Unknown building_id: {building_id!r}")
    elif sensor_id != BUILDINGS[building_id]["sensor_id"]:
        errors.append(f"sensor_id {sensor_id!r} is not registered to {building_id}")

    if not _is_number(voltage):
        errors.append("voltage must be a number")
    elif not (VOLTAGE_MIN <= voltage <= VOLTAGE_MAX):
        errors.append(f"voltage {voltage} outside {VOLTAGE_MIN}-{VOLTAGE_MAX} V")

    if not _is_number(current):
        errors.append("current must be a number")
    elif not (CURRENT_MIN <= current <= CURRENT_MAX):
        errors.append(f"current {current} outside {CURRENT_MIN}-{CURRENT_MAX} A")

    if errors:
        return None, errors

    return {
        "building_id": building_id,
        "sensor_id": sensor_id,
        "voltage": round(float(voltage), 2),
        "current": round(float(current), 2),
        "sensor_ts": str(payload.get("sensor_ts", ""))[:40],  # informational only
    }, []


# --------------------------------------------------------------------------
# 3. Power calculation (server-side: we never trust a client-sent power value)
#    Simplification: power factor assumed to be 1.0  ->  P(kW) = V x I / 1000
# --------------------------------------------------------------------------
def compute_power_kw(voltage, current):
    return round(voltage * current / 1000.0, 3)


# --------------------------------------------------------------------------
# 4. Anomaly detection
#    Rule 1 (threshold): power above the building's max_kw.
#    Rule 2 (baseline):  power above DEVIATION_FACTOR x average of recent
#                        NORMAL readings (anomalies are excluded so that a
#                        spike does not inflate the baseline).
# --------------------------------------------------------------------------
def compute_baseline(recent_normal_powers):
    """Average of the most recent normal readings, or None if too few."""
    window = list(recent_normal_powers)[:BASELINE_WINDOW]
    if len(window) < BASELINE_MIN_SAMPLES:
        return None
    return round(sum(window) / len(window), 3)


def detect_anomaly(building_id, power_kw, recent_normal_powers):
    """
    recent_normal_powers: power values of previous NORMAL readings for this
                          building, newest first.
    Returns dict: {status, reasons, baseline_kw}
    """
    reasons = []
    max_kw = BUILDINGS[building_id]["max_kw"]

    if power_kw > max_kw:
        reasons.append(f"THRESHOLD: {power_kw} kW exceeds limit {max_kw} kW")

    baseline = compute_baseline(recent_normal_powers)
    if baseline is not None and power_kw > DEVIATION_FACTOR * baseline:
        pct = round((power_kw / baseline - 1) * 100)
        reasons.append(f"DEVIATION: {power_kw} kW is {pct}% above baseline {baseline} kW")

    return {
        "status": "ANOMALY" if reasons else "NORMAL",
        "reasons": reasons,
        "baseline_kw": baseline,
    }


def process_reading(payload, recent_normal_powers):
    """Full pipeline used by both the Lambda and local tests.
    Returns (record, errors)."""
    clean, errors = validate_reading(payload)
    if errors:
        return None, errors
    clean["power_kw"] = compute_power_kw(clean["voltage"], clean["current"])
    clean.update(detect_anomaly(clean["building_id"], clean["power_kw"], recent_normal_powers))
    return clean, []
