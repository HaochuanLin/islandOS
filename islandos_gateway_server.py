"""Read-only HTTP telemetry ingress for islandOS.

The server validates sensor/gateway JSON messages, appends an audit trail, and
serves a same-origin read-only operator dashboard. It binds to loopback only.
It never writes PLC setpoints or actuator commands.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

from islandos_advisor import WEIGHT_PROFILES, evaluate_dispatch_rows
from islandos_io import apply_device_mapping, build_dispatch_input_rows, load_device_mapping, validate_telemetry


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>islandOS · Local Operator Review</title>
<style>
:root{color-scheme:light;--ink:#17332f;--muted:#5b716d;--line:#d7e3df;--panel:#fff;--bg:#f3f7f5;--accent:#176c5b;--warn:#8a4b08;--bad:#9b2525}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:24px max(20px,calc((100vw - 1100px)/2));background:#173f38;color:white}header h1{margin:0;font-size:clamp(24px,4vw,36px)}header p{margin:8px 0 0;color:#d7e9e3}
main{max-width:1100px;margin:24px auto;padding:0 16px 40px}.notice{padding:14px 16px;border:1px solid #e6cba1;background:#fff8e9;border-radius:12px;color:#69400d;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;min-width:0}.card h2{font-size:16px;margin:0 0 12px}.value{font-size:25px;font-weight:700;overflow-wrap:anywhere}.muted{color:var(--muted);font-size:13px}.status{font-weight:700}.good{color:var(--accent)}.warn{color:var(--warn)}.bad{color:var(--bad)}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}th{background:#f5f8f7}.table-wrap{overflow-x:auto}.pill{display:inline-block;border-radius:999px;padding:3px 9px;background:#e3efeb;font-size:12px;font-weight:700}
button{border:0;border-radius:9px;background:var(--accent);color:white;padding:10px 14px;font-weight:700;cursor:pointer}footer{margin-top:20px;color:var(--muted);font-size:13px}
@media(max-width:600px){header{padding:20px}main{margin-top:14px}.card{padding:14px}th,td{padding:8px}}
</style>
</head>
<body>
<header><h1>islandOS · Local Operator Review</h1><p>Live telemetry · energy–water dispatch advice · read-only prototype</p></header>
<main>
<div class="notice"><strong>Operator safety boundary:</strong> this dashboard provides advisory analysis only. It cannot write PLC setpoints or actuate equipment. Confirm sensor units, site limits, reserve margins, and operating procedures with the responsible engineer before acting.</div>
<div class="grid">
<section class="card"><h2>Gateway</h2><div id="gateway" class="value">Connecting…</div><div id="updated" class="muted">Waiting for status</div></section>
<section class="card"><h2>Renewable surplus</h2><div id="surplus" class="value">—</div><div class="muted">kW · source-defined surplus</div></section>
<section class="card"><h2>Freshwater demand</h2><div id="water" class="value">—</div><div class="muted">m³ per sample interval</div></section>
<section class="card"><h2>Cooling demand</h2><div id="cooling" class="value">—</div><div class="muted">kW thermal</div></section>
</div>
<section class="card" style="margin-top:14px"><h2>Dispatch advice</h2><label for="weight-profile">Operator objective priority</label> <select id="weight-profile"><option value="balanced">Balanced</option><option value="water_priority">Water priority</option><option value="cooling_priority">Cooling priority</option><option value="energy_efficiency">Energy efficiency</option></select><p class="muted">This changes the scoring weights, not physical constraints. Confirm the chosen priority with the operator.</p><p id="advice-status" class="status">Waiting for valid hourly telemetry…</p><p id="advice-reason" class="muted">At least two valid hourly-aligned samples and a fresh latest sample are required.</p><div class="table-wrap"><table><thead><tr><th>Policy</th><th>Eligible</th><th>Water unmet (m³)</th><th>Cooling unmet (kWhₜₕ)</th><th>Remaining surplus (kWh)</th><th>Constraint violations (h)</th></tr></thead><tbody id="policies"><tr><td colspan="6">No report available.</td></tr></tbody></table></div><p id="sensitivity" class="muted"></p></section>
<div style="display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap"><button id="refresh" type="button">Refresh now</button><button id="download-report" type="button" disabled>Download advice JSON</button><span id="checked" class="muted"></span></div>
<footer>Auto-refreshes every 15 seconds. Advice is based on the most recent available hourly window and a persistence forecast unless supplied forecasts exist. Software validation is not field validation. Physical writes: disabled.</footer>
</main>
<script>
const byId=id=>document.getElementById(id);let lastReport=null;
const fmt=(v,d=2)=>Number.isFinite(Number(v))?Number(v).toLocaleString(undefined,{maximumFractionDigits:d}):"—";
function setText(id,value){byId(id).textContent=value==null?"—":String(value)}
async function getJson(path){const r=await fetch(path,{cache:"no-store"});let data={};try{data=await r.json()}catch{}if(!r.ok){const e=new Error(data.error||("HTTP "+r.status));e.status=r.status;e.data=data;throw e}return data}
async function refresh(){
 setText("checked","Checking…");
 try{
  const health=await getJson("/health");setText("gateway",health.status==="ok"?"ONLINE":"UNKNOWN");byId("gateway").className="value good";
  try{
   const latest=await getJson("/latest");const v=latest.values||{};
   setText("surplus",fmt(v.renewable_surplus_kw));setText("water",fmt(v.water_demand_m3));setText("cooling",fmt(v.cooling_demand_kw_th));
   setText("updated","Latest sample: "+(latest.timestamp_utc||"unknown")+" · "+(latest.device_id||latest.source||"device"));
  }catch(e){setText("surplus","—");setText("water","—");setText("cooling","—");setText("updated",e.message)}
  try{
   const report=await getJson("/advice?weight_profile="+encodeURIComponent(byId("weight-profile").value));lastReport=report;byId("download-report").disabled=false;
   const winner=report.recommended_policy_for_operator_review;
   setText("advice-status",winner?"Candidate for operator review: "+winner:"No policy recommendation — operator review required");
   byId("advice-status").className="status "+(winner?"good":"warn");
   setText("advice-reason",report.recommendation_reason||"No recommendation reason supplied.");
   const body=byId("policies");body.replaceChildren();
   (report.policy_comparison||[]).forEach(row=>{
    const tr=document.createElement("tr");
    [row.policy,row.eligible_for_recommendation?"Yes":"No",fmt(row.water_unmet_m3),fmt(row.cooling_unmet_kwh_th),fmt(row.remaining_surplus_kwh),fmt(row.constraint_violation_hours,0)].forEach(value=>{const td=document.createElement("td");td.textContent=String(value);tr.appendChild(td)});
    body.appendChild(tr);
   });
   setText("sensitivity","Weight-sensitivity winner counts (this input only, not confidence): "+JSON.stringify(report.weight_sensitivity_winner_counts||{}));
  }catch(e){
   lastReport=null;byId("download-report").disabled=true;setText("advice-status",e.status===409?"Waiting for fresh, hourly-aligned telemetry":"Advice unavailable");
   byId("advice-status").className="status warn";
   setText("advice-reason",e.message+(e.data&&e.data.details?": "+e.data.details.join("; "):""));
   byId("policies").replaceChildren();const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=6;td.textContent="No dispatch recommendation available.";tr.appendChild(td);byId("policies").appendChild(tr);setText("sensitivity","");
  }
 }catch(e){setText("gateway","OFFLINE");byId("gateway").className="value bad";setText("updated",e.message)}
 setText("checked","Last checked: "+new Date().toLocaleTimeString());
}
byId("refresh").addEventListener("click",refresh);byId("weight-profile").addEventListener("change",refresh);
byId("download-report").addEventListener("click",()=>{if(!lastReport)return;const blob=new Blob([JSON.stringify(lastReport,null,2)+"\n"],{type:"application/json"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="islandos-dispatch-advice.json";a.click();URL.revokeObjectURL(url)});
refresh();setInterval(refresh,15000);
</script>
</body></html>"""


def _json_bytes(payload):
    return (json.dumps(payload, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def make_handler(audit_path, source, max_age_seconds, mapping=None, bearer_token=None):
    audit_path = Path(audit_path)
    lock = threading.Lock()
    latest = {"record": None}

    class Handler(BaseHTTPRequestHandler):
        server_version = "IslandOSReadOnlyGateway/1.0"

        def _send(self, status, payload):
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, status, body):
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(encoded)

        def _authorized(self):
            if not bearer_token:
                return True
            supplied = self.headers.get("Authorization", "")
            expected = "Bearer " + bearer_token
            return hmac.compare_digest(supplied, expected)

        def do_GET(self):
            request_url = urlparse(self.path)
            path = request_url.path
            if path not in ("/health", "/latest", "/advice", "/dashboard"):
                self._send(404, {"error": "not found"})
                return
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            if path == "/dashboard":
                self._send_html(200, _DASHBOARD_HTML)
                return
            if path == "/health":
                self._send(200, {
                    "status": "ok",
                    "mode": "read_only_telemetry_ingest",
                    "device_mapping_loaded": mapping is not None,
                    "mapping_schema_version": mapping.get("schema_version") if mapping else None,
                    "mapped_canonical_fields": sorted(mapping.get("fields", {})) if mapping else [],
                    "physical_write_performed": False,
                })
                return
            if path == "/advice":
                weight_profile = parse_qs(request_url.query).get("weight_profile", ["balanced"])[0]
                if weight_profile not in WEIGHT_PROFILES:
                    self._send(400, {
                        "error": "unknown weight_profile; choose one of " + ", ".join(WEIGHT_PROFILES),
                        "physical_write_performed": False,
                    })
                    return
                records = deque(maxlen=24)
                try:
                    with lock:
                        if audit_path.exists():
                            with audit_path.open("r", encoding="utf-8") as stream:
                                for line in stream:
                                    if line.strip():
                                        records.append(json.loads(line))
                except (OSError, json.JSONDecodeError) as exc:
                    self._send(500, {"error": "could not read telemetry audit: " + str(exc)})
                    return
                if len(records) < 2:
                    self._send(409, {
                        "error": "at least two valid hourly telemetry rows are required",
                        "physical_write_performed": False,
                    })
                    return
                latest_record = records[-1]
                latest_payload = {"timestamp_utc": latest_record.get("timestamp_utc"), **latest_record.get("values", {})}
                freshness = validate_telemetry(
                    latest_payload, source=source,
                    received_at=datetime.now(timezone.utc),
                    max_age_seconds=max_age_seconds,
                )
                if not freshness.valid:
                    self._send(409, {
                        "error": "latest telemetry is not fresh",
                        "details": list(freshness.errors),
                        "physical_write_performed": False,
                    })
                    return
                try:
                    dispatch_rows = build_dispatch_input_rows(list(records))
                    report = evaluate_dispatch_rows(dispatch_rows, name="http-gateway-live-window", weight_profile=weight_profile)
                except (TypeError, ValueError) as exc:
                    self._send(422, {
                        "error": "telemetry is not dispatch-ready: " + str(exc),
                        "physical_write_performed": False,
                    })
                    return
                report.update({
                    "mode": "loopback_http_telemetry",
                    "data_status": "validated telemetry; site calibration not verified",
                    "source": source,
                    "row_count": len(dispatch_rows),
                    "forecast_method": "persistence baseline; first row cold-start seeded",
                    "operator_action_required": True,
                    "physical_write_performed": False,
                })
                self._send(200, report)
                return
            with lock:
                record = latest["record"]
            if record is None:
                self._send(404, {"error": "no valid telemetry received yet"})
            else:
                self._send(200, record)

        def do_POST(self):
            if urlparse(self.path).path != "/telemetry":
                self._send(404, {"error": "not found"})
                return
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send(415, {"error": "Content-Type must be application/json"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, {"error": "invalid Content-Length"})
                return
            if content_length <= 0 or content_length > 65536:
                self._send(413, {"error": "request body must be between 1 and 65536 bytes"})
                return
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(400, {"error": "body must be valid UTF-8 JSON"})
                return
            if not isinstance(payload, dict):
                self._send(400, {"error": "body must be a JSON object"})
                return
            try:
                canonical_payload = apply_device_mapping(payload, mapping) if mapping else payload
                frame = validate_telemetry(
                    canonical_payload,
                    source=source,
                    received_at=datetime.now(timezone.utc),
                    max_age_seconds=max_age_seconds,
                )
            except (TypeError, ValueError) as exc:
                self._send(400, {"error": str(exc)})
                return
            record = frame.as_dict()
            record["received_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            record["physical_write_performed"] = False
            if not frame.valid:
                self._send(422, {
                    "status": "rejected",
                    "valid": False,
                    "errors": list(frame.errors),
                    "warnings": list(frame.warnings),
                    "physical_write_performed": False,
                })
                return
            try:
                with lock:
                    audit_path.parent.mkdir(parents=True, exist_ok=True)
                    with audit_path.open("a", encoding="utf-8") as stream:
                        stream.write(_json_bytes(record).decode("utf-8"))
                    latest["record"] = record
            except OSError as exc:
                self._send(500, {"error": "could not persist telemetry audit: " + str(exc)})
                return
            self._send(202, {
                "status": "accepted",
                "valid": True,
                "timestamp_utc": record["timestamp_utc"],
                "audit_file": str(audit_path),
                "physical_write_performed": False,
            })

        def log_message(self, format_string, *args):
            # Keep the console useful but avoid dumping raw telemetry payloads.
            super().log_message(format_string, *args)

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--source", default="http-gateway")
    parser.add_argument("--audit-file", default="build/telemetry/http-ingest-audit.jsonl")
    parser.add_argument("--mapping", help="Optional vendor field/unit mapping JSON")
    parser.add_argument("--max-age-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.max_age_seconds < 0:
        parser.error("--max-age-seconds must be non-negative")
    if args.host not in _LOOPBACK_HOSTS:
        parser.error(
            "bind only to loopback; use a site-approved authenticated TLS reverse proxy "
            "or local device adapter for remote clients"
        )

    try:
        mapping = load_device_mapping(args.mapping) if args.mapping else None
    except (OSError, ValueError) as exc:
        parser.error("could not load device mapping: %s" % exc)

    bearer_token = os.environ.get("ISLANDOS_GATEWAY_TOKEN", "")
    handler = make_handler(args.audit_file, args.source, args.max_age_seconds, mapping, bearer_token or None)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print("IslandOS read-only telemetry gateway listening on http://%s:%d" % (args.host, args.port), flush=True)
    print("No PLC commands or actuator writes are supported.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
