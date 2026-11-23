# frontend

One Vite project with two entries. `npm run build` writes both into `frontend/dist/`, which is not
committed.

| Entry | Source | Output | What it is |
|---|---|---|---|
| `index.html` | `src/main.tsx` → `src/App.tsx` | `dist/index.html` | the customer console: sign-in, sites, telemetry, notifications, membership |
| `application-views.html` | `src/applicationViewsMain.tsx` → `src/ApplicationViews.tsx` | `dist/application-views.html` | the contract viewer: a local, read-only tool |

Both call `src/contracts.ts`, which is generated from the Python contract by `python -m
islandos_core.contract_schemas --typescript` and must stay byte-identical to it
(`tests/test_contract_typescript.py`). Never hand-edit that file.

## The viewer is a local tool, not a console page

This is the recorded decision for the "local tool or third console route" question, so it is not
re-opened by every later change:

- **It is a local tool.** It runs on the operator's machine against a report file they picked and a
  loopback transport they started. It has no login, no `/api` proxy, no tenant, and no deployment.
- **It is not a console route.** The console's footer carries one read-only link to it
  (`src/App.tsx`, `Contract viewer (read only) ↗`); nothing else about the console changed, and the
  sign-in flow is untouched.
- Option B — fold it into the console as a third route — was rejected. It would require a session
  check the viewer has no use for, an `/api` proxy entry, token plumbing, error states that only exist
  to satisfy auth, and page tests for a surface that has no signed-in data. A route also implies a
  hosted service, which this is not. Revisit only if someone needs to open a report with no local
  checkout at all.

## How to open it

**Recommended — one command, one origin.** From the repository root:

```bash
cd frontend
npm install
npm run build
cd ..
python -m islandos_core.transport   # with the repository's .venv active, see the root README
```

Then open **http://127.0.0.1:8765/**. The transport serves the built page at `GET /` and its files
under `GET /assets/<file>` from `frontend/dist/assets` only, so the page and its `/contracts` read
share one origin. Without a build, `GET /` answers `404` with the `npm run build` hint instead of an
empty page. `GET /application-views.html` returns the same page byte for byte, so a bookmark of either
URL works. The page reads `/contracts` from the origin that served it and falls back to
`http://127.0.0.1:8765`, so `--port 8799` needs no edit and `npm run dev` still reaches the default
transport.

Two surfaces, two servers. The transport serves the viewer and nothing else: `GET /index.html`
answers `404`, so `http://127.0.0.1:8765/` never lands on the console. The console is its own server
(`npm run dev`, or `npm run preview` over the same build), and only there does the footer link have a
console page to sit on. If 8765 is taken, pass `--port 8799`; `Ctrl+C` stops it, and nothing survives
the run.

**From the console.** Start the console as usual (`npm run dev` in `frontend/`, against the local
reference API). After sign-in, the footer link opens `application-views.html` from the same build.
The page's `/contracts` read is then cross-origin on loopback, which `GET /contracts` allows on
purpose. `npm run preview` works the same way.

**From disk.** Opening `frontend/dist/application-views.html` directly works, but report loading is
all that page can do from `file://`; start the transport if you also want the schema tables.

## What you see

- **A downloaded report.** Pages 05, 06 and 09 write their contract views into the JSON they offer
  for download under `application_views`. Drop that file on the page and it renders:
  - the **request** — page, schema version, hour count, site digest, provenance, request SHA-256;
  - the **result** — 05/06 show the recommended policy, 24 h energy cost, unmet load, service
    equivalence and whether the savings claim was withheld; 09 shows the device schedule's critical
    and flexible energy, peak task demand, charge, and the earliest-feasible reference;
  - the **annual projection** — present only when the 06 download carries one (it is `null` until the
    reader declares the equal-days assumption).
- **The contract itself.** "Load contracts" reads `GET /contracts` and prints `run_request`,
  `run_result_summary`, `device_flexibility_summary` and `annual_projection` field by field with type,
  unit, nullability and owner. The tables are built from the response's own keys in its own order, so a
  contract added to `/contracts` shows up without a code change.
- Nothing else. There is no report browser, no history, no search.

## What it does not do

**The viewer does not compute and does not write.** Every number on the page is copied from the
`application_views` block or the schema response and only formatted for display (`toFixed`,
`toLocaleString`, digest truncation). The page never runs a forecast, an optimiser, an annualisation
or an economic calculation, and it never sends `POST /run`.

Concretely:

- **No writes.** No device command, no file save, no `localStorage`, no server-side state. The report
  file is read in the browser with `File.text()` and is not uploaded anywhere.
- **No validation of its own.** It checks that `request` and `result` exist, then displays what is
  there; a file without an `application_views` block is rejected with a readable message rather than
  guessed at. Field rules and units are owned by the Python contract, not re-implemented here.
- **No console data.** No sites, telemetry, notifications, members or sessions. The viewer opens
  before any sign-in and keeps working after sign-out.
- **No annual projection for 09.** 09 downloads carry `annual: null`; the page shows the device
  schedule only.
- **No deployment.** Loopback only, no authentication, no persistence — the same limits the transport
  documents for itself.

## Where the boundary sits

| Concern | Console (`index.html`) | Viewer (`application-views.html`) |
|---|---|---|
| Identity | signed-in session, `Authorization: Bearer` | none |
| Data | `/api/v1` (sites, telemetry, notifications, members) | a file the user picks + `GET /contracts` |
| Writes | site, membership and notification changes | none |
| Numbers | API output | the report's already-built `application_views` block |
| Deployment | local reference API, loopback | local transport, loopback, not deployed |

If a change would give the viewer a session, a write path or a server-side store, it belongs in the
console instead, and the answer above has been reversed by accident.

## Verification

```bash
cd frontend && npm run build          # tsc -b && vite build; both entries land in dist/
python -m islandos_core.transport     # from the repository root
curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' http://127.0.0.1:8765/
curl -sS http://127.0.0.1:8765/contracts | head -c 200
pytest tests/test_application_transport.py
```

The transport test serves a temporary build, checks the HTML/JS content types, refuses
`assets/../…` traversal, and covers the missing-build `404`. For the console entry, open the console
after `npm run dev` and follow the footer link; the target is `application-views.html` from the same
build.

Measured on `a5ef3df` from a clean worktree, transport on `--port 8799`:

| Check | Result |
|---|---|
| `npm run build` | 35 modules transformed; `dist/application-views.html` 0.67 kB; `assets/application-views-*.js` 8.83 kB |
| `GET /` | 200, 672 B |
| `GET /application-views.html` | 200, 672 B, identical to `/` |
| `GET /assets/application-views-*.js` | 200, 8 832 B |
| `GET /contracts` | 200, 10 902 B |
| `GET /index.html` | 404 |
| `GET /assets/../index.html` | 404 |
| `pytest` transport + integration doc + contract TS + contract schema | 42 passed |
| built console bundle | contains `application-views.html` and `Contract viewer`, so the footer link survives the build |

Loading a real 09 download on that build shows `72.0` / `17.0` / `6.0` / `13.77 USD` against the
`103.2 kWh · 15.44 USD` earliest-feasible reference, and `Load contracts` fills the `run_request`,
`run_result_summary`, `device_flexibility_summary` and `annual_projection` tables from the same
origin.
