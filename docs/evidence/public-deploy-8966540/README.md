# Public deployment check — build 8966540

Public Streamlit app, checked 2026-11-24 after the shared-history hash change.

- Build stamp: `8966540 (git)`, shown in the page footer / sidebar.
- Page 05: `24.52 USD`, `0.00 kWh`, `10.55 USD`, `Shared history SHA-256`
  `7012014ef720e5802d1ff9147fe439b93d52736f47c538170da46d55b6d2ed70`.
- Page 06: same `Shared history SHA-256`; annual projection remains withheld by default until the
  reader declares the equal-days assumption. With that assumption, the pinned annual figures are
  `7,709.55 USD/year` and `186,150 kWh`; this is also asserted by the local Python suite.
- Page 09: renders normally; `72 kWh` critical energy, `17 kWh` flexible task, `13.77 USD`,
  no exception.
- No `ImportError`, exception panel or error banner appeared on 05, 06 or 09.

The hash is the same as the local pinned hash in `tests/test_demo_site_history.py`. The public app
was rebuilt after a stale module cache produced an old hash; the screenshots here are from the clean
rebuild, not the pre-rebuild process.

## Files

| File | Shows |
|---|---|
| `00-build-stamp.png` | Public workspace with `build 8966540 (git)`. |
| `05-decision-dashboard.png` | Page 05 with the shared hash and `24.52 / 10.55 USD`. |
| `06-joint-optimizer.png` | Page 06 with the same shared hash. |
| `09-device-planner.png` | Page 09 with its default device schedule. |
