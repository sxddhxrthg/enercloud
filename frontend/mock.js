// MOCK DATA ONLY - used before the AWS API exists, and clearly labelled in the UI.
// Shape matches the GET /dashboard response contract (docs/api-contract.md).
const MOCK_BUILDINGS = [
  { building_id: "ACAD-A",   name: "Academic Block A", type: "Classrooms",     sensor_id: "SEN-ACAD-A-01",   normal_min_kw: 3.0, normal_max_kw: 6.0, max_kw: 9.0 },
  { building_id: "LAB-1",    name: "Computer Lab 1",   type: "Laboratory",     sensor_id: "SEN-LAB-1-01",    normal_min_kw: 2.0, normal_max_kw: 4.0, max_kw: 6.0 },
  { building_id: "LIB",      name: "Central Library",  type: "Library",        sensor_id: "SEN-LIB-01",      normal_min_kw: 1.5, normal_max_kw: 3.0, max_kw: 5.0 },
  { building_id: "HOSTEL-A", name: "Hostel A",         type: "Hostel",         sensor_id: "SEN-HOSTEL-A-01", normal_min_kw: 4.0, normal_max_kw: 8.0, max_kw: 12.0 },
  { building_id: "ADMIN",    name: "Admin Block",      type: "Administration", sensor_id: "SEN-ADMIN-01",    normal_min_kw: 1.0, normal_max_kw: 2.5, max_kw: 4.0 },
];

function mockReading(b, minutesAgo, spike) {
  const mid = (b.normal_min_kw + b.normal_max_kw) / 2;
  const kw = spike ? b.max_kw * 1.45 : mid * (0.85 + Math.random() * 0.3);
  const voltage = +(228 + Math.random() * 5).toFixed(1);
  const current = +((kw * 1000) / voltage).toFixed(2);
  const power_kw = +((voltage * current) / 1000).toFixed(3);
  const ts = new Date(Date.now() - minutesAgo * 60000).toISOString();
  return {
    building_id: b.building_id, sensor_id: b.sensor_id, ts, voltage, current, power_kw,
    status: spike ? "ANOMALY" : "NORMAL",
    reasons: spike ? [`THRESHOLD: ${power_kw} kW exceeds limit ${b.max_kw} kW`] : [],
    baseline_kw: +mid.toFixed(3),
  };
}

function buildMockDashboard() {
  const recent = [];
  MOCK_BUILDINGS.forEach((b) => {
    for (let i = 5; i >= 0; i--) recent.push(mockReading(b, i, b.building_id === "LAB-1" && i === 0));
  });
  recent.sort((a, b) => (a.ts < b.ts ? 1 : -1));
  const buildings = MOCK_BUILDINGS.map((b) => ({
    ...b, latest: recent.find((r) => r.building_id === b.building_id) || null,
  }));
  const anomalies = recent.filter((r) => r.status === "ANOMALY");
  return {
    generated_at: new Date().toISOString(),
    summary: {
      total_buildings: buildings.length,
      active_sensors: buildings.filter((b) => b.latest).length,
      total_power_kw: +buildings.reduce((s, b) => s + (b.latest ? b.latest.power_kw : 0), 0).toFixed(3),
      anomaly_count: anomalies.length,
      readings_count: recent.length,
    },
    buildings,
    recent_readings: recent.slice(0, 20),
    anomalies,
  };
}
