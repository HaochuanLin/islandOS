import { useState } from "react";
import type { ChangeEvent } from "react";
import "./styles.css";

type Field = {
  name: string;
  type: string;
  unit: string;
  nullable: boolean;
  owner: string;
};

type Contract = { fields: Field[]; nested?: Record<string, Field[]> };

type Schema = {
  contract_version: number;
  contracts: {
    run_request: Contract;
    run_result_summary: Contract;
    annual_projection: Contract;
  };
};

type Views = {
  request: Record<string, unknown>;
  result: Record<string, unknown>;
  annual: Record<string, unknown> | null;
};

const TRANSPORT = "http://127.0.0.1:8765";

function readViews(payload: unknown): Views {
  if (!payload || typeof payload !== "object") throw new Error("The file is not a JSON object.");
  const record = payload as Record<string, unknown>;
  const source = record.application_views ?? record;
  if (!source || typeof source !== "object") {
    throw new Error("No application_views block: load a report downloaded from page 05 or 06.");
  }
  const views = source as Record<string, unknown>;
  if (!views.request || !views.result) {
    throw new Error("The block must carry both request and result.");
  }
  return {
    request: views.request as Record<string, unknown>,
    result: views.result as Record<string, unknown>,
    annual: (views.annual as Record<string, unknown> | null | undefined) ?? null,
  };
}

function FieldTable({ title, fields }: { title: string; fields: Field[] }) {
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
  const [schema, setSchema] = useState<Schema | null>(null);
  const [views, setViews] = useState<Views | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("not loaded");

  async function loadContracts() {
    setStatus("loading");
    try {
      const response = await fetch(`${TRANSPORT}/contracts`);
      if (!response.ok) throw new Error(`transport answered ${response.status}`);
      setSchema((await response.json()) as Schema);
      setStatus("contracts loaded");
    } catch (reason) {
      setStatus("contracts unavailable");
      setError(
        `Could not reach ${TRANSPORT}/contracts. Start it with "python -m islandos_core.transport". ` +
          String(reason),
      );
    }
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
  const site = request?.site as Record<string, unknown> | undefined;
  const history = request?.history as Record<string, unknown> | undefined;
  const result = views?.result;
  const annual = views?.annual;
  const figures = annual?.figures as Record<string, number> | undefined;
  const basis = annual?.basis as Record<string, unknown> | undefined;

  return (
    <main>
      <header className="topbar">
        <div>
          <p className="eyebrow">APPLICATION VIEWS · READ ONLY</p>
          <h1>Contract viewer</h1>
        </div>
        <div className="top-actions">
          <span className="api-status">
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
            It renders a report downloaded from page 05 or 06 and the schema served by the local
            transport. It does not run a forecast, an optimiser, or any economic calculation, and it
            writes nothing.
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
        <input type="file" accept="application/json,.json" onChange={loadReport} />
        {error ? <p className="error">{error}</p> : null}
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
              <p className="eyebrow">RESULT SUMMARY</p>
              <h2>{String(result.recommended_policy_label)}</h2>
            </div>
            <span className="tag">{String(result.page)}</span>
          </div>
          <div className="metric-grid">
            <article className="metric">
              <span>Estimated 24h energy cost</span>
              <strong>
                {result.estimated_24h_energy_cost === null
                  ? "—"
                  : `${Number(result.estimated_24h_energy_cost).toFixed(2)} ${String(result.currency ?? "")}`}
              </strong>
            </article>
            <article className="metric">
              <span>Unmet load</span>
              <strong>
                {result.unmet_load_kwh === null ? "—" : `${Number(result.unmet_load_kwh).toFixed(2)} kWh`}
              </strong>
            </article>
            <article className="metric">
              <span>Service equivalent</span>
              <strong>{result.service_equivalent === null ? "—" : String(result.service_equivalent)}</strong>
            </article>
            <article className="metric">
              <span>Savings claim</span>
              <strong>{result.savings_claim_withheld ? "withheld" : "shown"}</strong>
            </article>
          </div>
          <p className="eyebrow">RUN ID</p>
          <p>{String(result.run_id ?? "—")}</p>
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
              <strong>{Number(figures.annual_load_energy_kwh).toLocaleString()} kWh</strong>
            </article>
            <article className="metric">
              <span>Annual energy cost</span>
              <strong>{Number(figures.annual_energy_cost).toFixed(2)}</strong>
            </article>
            <article className="metric">
              <span>Equipment operating cost</span>
              <strong>{Number(figures.annual_equipment_operating_cost).toFixed(2)}</strong>
            </article>
            <article className="metric">
              <span>Diesel run hours</span>
              <strong>{Number(figures.annual_diesel_run_hours).toFixed(0)} h</strong>
            </article>
          </div>
          <p>{String(annual.scope ?? "")}</p>
        </section>
      ) : null}

      {schema ? (
        <>
          <FieldTable title="run_request" fields={schema.contracts.run_request.fields} />
          <FieldTable title="run_result_summary" fields={schema.contracts.run_result_summary.fields} />
          <FieldTable title="annual_projection" fields={schema.contracts.annual_projection.fields} />
        </>
      ) : null}
    </main>
  );
}

export default App;
