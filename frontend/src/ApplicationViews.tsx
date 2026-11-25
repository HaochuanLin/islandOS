import { useState } from "react";
import type { ChangeEvent } from "react";
import type { ContractField, ContractSchema, DeviceFlexibilitySummary, RunResultSummary } from "./contracts";
import { readViews } from "./applicationViewsPayload";
import type { Views } from "./applicationViewsPayload";
import "./styles.css";

const TRANSPORT = "http://127.0.0.1:8765";

/**
 * Where `/contracts` lives. When the transport serves this page, its own origin is the only one that
 * can answer, so `--port 8799` works without editing this file. Under `npm run dev` / `preview` and
 * from `file://` the page is not on the transport, so keep the documented default.
 */
function transportBases(): string[] {
  const here = window.location.origin;
  const sameOrigin = /^http/.test(here) && here !== TRANSPORT ? here : null;
  return sameOrigin ? [sameOrigin, TRANSPORT] : [TRANSPORT];
}

function format(value: number | null | undefined, digits: number): string {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "—";
}

function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : "—";
}

function annualUnavailableCopy(page: string | undefined): string {
  switch (page) {
    case "customer_dashboard":
      return "This report has no annual projection. The 05 investment screen uses its own entered annual bills, not the 06 operating projection.";
    case "joint_resource_optimizer":
      return "The equal-days assumption was not declared for this run, so no annual projection is included.";
    case "device_flexibility_planner":
      return "09 is a 24-hour device schedule; it has no annual projection.";
    default:
      return "No annual projection is included in this report.";
  }
}

function FieldTable({ title, fields }: { title: string; fields: ContractField[] }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <p className="eyebrow">CONTRACT</p>
          <h2>{title}</h2>
        </div>
        <span className="tag">{fields.length} FIELDS</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Field</th>
            <th>Type</th>
            <th>Unit</th>
            <th>Nullable</th>
            <th>Owner</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((field) => (
            <tr key={field.name}>
              <td>{field.name}</td>
              <td>{field.type}</td>
              <td>{field.unit}</td>
              <td>{field.nullable ? "yes" : "no"}</td>
              <td>{field.owner}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function App() {
  const [schema, setSchema] = useState<ContractSchema | null>(null);
  const [views, setViews] = useState<Views | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("not loaded");

  async function loadContracts() {
    setStatus("loading");
    const bases = transportBases();
    let lastReason: unknown = null;
    for (const base of bases) {
      try {
        const response = await fetch(`${base}/contracts`);
        if (!response.ok) throw new Error(`${base}/contracts answered ${response.status}`);
        setSchema((await response.json()) as ContractSchema);
        setError(null);
        setStatus("contracts loaded");
        return;
      } catch (reason) {
        lastReason = reason;
      }
    }
    setStatus("contracts unavailable");
    setError(
      `Could not read /contracts from ${bases.join(" or ")}. Start it with ` +
        `"python -m islandos_core.transport" and reload. ${String(lastReason)}`,
    );
  }

  async function loadReport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      setViews(readViews(JSON.parse(await file.text())));
      setError(null);
    } catch (reason) {
      setViews(null);
      setError(String(reason));
    }
  }

  const request = views?.request;
  const site = request?.site;
  const history = request?.history;
  const result = views?.result;
  const annual = views?.annual;
  const figures = annual?.figures;
  const basis = annual?.basis;
  // 09's result is a device schedule summary, not a policy summary: different fields, same
  // "display what the Python side already decided" rule.
  const planner =
    request?.page === "device_flexibility_planner" && result
      ? (result as unknown as DeviceFlexibilitySummary)
      : null;
  const summary = planner ? null : (result as RunResultSummary | undefined);

  return (
    <main className="viewer">
      <header className="topbar">
        <div>
          <p className="eyebrow">APPLICATION VIEWS · READ ONLY</p>
          <h1>Contract viewer</h1>
        </div>
        <div className="top-actions">
          <span className="api-status" aria-live="polite">
            <span className={schema ? "dot good" : "dot"} />
            {status}
          </span>
          <button className="outline" onClick={loadContracts}>
            Load contracts
          </button>
        </div>
      </header>

      <section className="notice">
        <span className="notice-icon">i</span>
        <div>
          <strong>This page only reads shapes</strong>
          <p>
            It renders a report downloaded from page 05, 06 or 09 and the schema served by the
            local transport. It does not run a forecast, an optimiser, or any economic
            calculation, and it writes nothing.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="eyebrow">INPUT</p>
            <h2>Load a downloaded report</h2>
          </div>
          <span className="tag">{views ? "VIEWS LOADED" : "NO FILE"}</span>
        </div>
        <input
          type="file"
          accept="application/json,.json"
          aria-label="Report JSON file"
          onChange={loadReport}
        />
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
      </section>

      {request ? (
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">REQUEST</p>
              <h2>{String(request.page)}</h2>
            </div>
            <span className="tag">SCHEMA v{String(request.schema_version)}</span>
          </div>
          <div className="metric-grid">
            <article className="metric">
              <span>Hours</span>
              <strong>{String(history?.hour_count ?? "—")}</strong>
            </article>
            <article className="metric">
              <span>Site digest</span>
              <strong>{String(site?.digest ?? "—").slice(0, 12)}</strong>
            </article>
            <article className="metric">
              <span>Provenance</span>
              <strong>{String(history?.provenance ?? "—")}</strong>
            </article>
            <article className="metric">
              <span>Request SHA-256</span>
              <strong>{String(request.request_sha256 ?? "—").slice(0, 12)}</strong>
            </article>
          </div>
        </section>
      ) : null}

      {result ? (
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">{planner ? "DEVICE SCHEDULE SUMMARY" : "RESULT SUMMARY"}</p>
              <h2>{planner ? String(planner.method) : String(summary?.recommended_policy_label)}</h2>
            </div>
            <span className="tag">{planner ? String(planner.page) : String(summary?.page)}</span>
          </div>
          {planner ? (
            <div className="metric-grid">
              <article className="metric">
                <span>Critical energy</span>
                <strong>{format(planner.critical_energy_kwh, 1)} kWh</strong>
              </article>
              <article className="metric">
                <span>Flexible task energy</span>
                <strong>{format(planner.flexible_task_energy_kwh, 1)} kWh</strong>
              </article>
              <article className="metric">
                <span>Peak task demand</span>
                <strong>{format(planner.peak_task_demand_kw, 1)} kW</strong>
              </article>
              <article className="metric">
                <span>Scheduled energy charge</span>
                <strong>
                  {format(planner.scheduled_energy_charge, 2)} {String(planner.currency ?? "")}
                </strong>
              </article>
            </div>
          ) : (
            <div className="metric-grid">
              <article className="metric">
                <span>Estimated 24h energy cost</span>
                <strong>
                  {summary?.estimated_24h_energy_cost === null
                    ? "—"
                    : `${format(summary?.estimated_24h_energy_cost, 2)} ${String(summary?.currency ?? "")}`}
                </strong>
              </article>
              <article className="metric">
                <span>Unmet load</span>
                <strong>
                  {summary?.unmet_load_kwh === null ? "—" : `${format(summary?.unmet_load_kwh, 2)} kWh`}
                </strong>
              </article>
              <article className="metric">
                <span>Service equivalent</span>
                <strong>{summary?.service_equivalent === null ? "—" : String(summary?.service_equivalent)}</strong>
              </article>
              <article className="metric">
                <span>Savings claim</span>
                <strong>{summary?.savings_claim_withheld ? "withheld" : "shown"}</strong>
              </article>
            </div>
          )}
          {planner ? (
            <>
              <p className="eyebrow">EARLIEST-FEASIBLE REFERENCE</p>
              <p>
                {format(planner.reference_grid_import_kwh, 1)} kWh ·{" "}
                {format(planner.reference_estimated_energy_cost, 2)} {String(planner.currency ?? "")} · unmet{" "}
                {format(planner.critical_unmet_load_kwh, 2)} kWh · shed{" "}
                {format(planner.flexible_load_shed_kwh, 2)} kWh
              </p>
              <p className="eyebrow">SUMMARY SHA-256</p>
              <p>{String(planner.summary_sha256).slice(0, 12)}</p>
            </>
          ) : (
            <>
              <p className="eyebrow">RUN ID</p>
              <p>{String(summary?.run_id ?? "—")}</p>
            </>
          )}
        </section>
      ) : null}

      {annual && figures ? (
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">ANNUAL PROJECTION</p>
              <h2>Declared assumption</h2>
            </div>
            <span className="tag">{String(basis?.days_equivalent_per_year ?? "—")} DAYS / YEAR</span>
          </div>
          <div className="metric-grid">
            <article className="metric">
              <span>Annual load energy</span>
              <strong>{formatCount(figures.annual_load_energy_kwh)} kWh</strong>
            </article>
            <article className="metric">
              <span>Annual energy cost</span>
              <strong>{format(figures.annual_energy_cost, 2)}</strong>
            </article>
            <article className="metric">
              <span>Equipment operating cost</span>
              <strong>{format(figures.annual_equipment_operating_cost, 2)}</strong>
            </article>
            <article className="metric">
              <span>Diesel run hours</span>
              <strong>{format(figures.annual_diesel_run_hours, 0)} h</strong>
            </article>
          </div>
          <p>{String(annual.scope ?? "")}</p>
        </section>
      ) : (
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">ANNUAL PROJECTION</p>
              <h2>Not included in this report</h2>
            </div>
          </div>
          <p>{annualUnavailableCopy(request?.page)}</p>
        </section>
      )}

      {schema ? (
        <>
          {Object.entries(schema.contracts).map(([name, body]) => (
            <FieldTable key={name} title={name} fields={body.fields} />
          ))}
        </>
      ) : null}
    </main>
  );
}

export default App;
