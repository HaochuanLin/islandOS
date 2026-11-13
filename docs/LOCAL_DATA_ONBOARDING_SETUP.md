# Local customer data onboarding

The Streamlit app includes a **Data onboarding & workspace** page for CSV and XLSX inspection. The public hosted demo can inspect files in memory and export a JSON inspection report. It deliberately does not persist customer metadata because the public demo has no customer authentication or tenant isolation.

## Run a private local workspace

Use a trusted local checkout and a private machine. From the repository root:

```bash
# Windows PowerShell
$env:ISLANDOS_ENABLE_LOCAL_WORKSPACE = "1"
$env:ISLANDOS_WORKSPACE_DB = ".islandos/workspace.sqlite3"
streamlit run app.py
```

```bash
# macOS / Linux
ISLANDOS_ENABLE_LOCAL_WORKSPACE=1 \
ISLANDOS_WORKSPACE_DB=.islandos/workspace.sqlite3 \
streamlit run app.py
```

The workspace database is local and single-user. It records project metadata, uploaded file basename, media type, provenance, quality status, worksheet, row/signal counts and the original file SHA-256. It does **not** retain uploaded file bytes.

## Import review flow

1. Upload a CSV or XLSX file.
2. Select the actual provenance class: measured, customer-provided, public reanalysis, synthetic, forecast, vendor specification, or inferred.
3. Review suggested mappings, explicit/assumed units, timestamp checks, missing values, and quality findings.
4. Review task gates for exploration, forecasting and dispatch screening.
5. Download the JSON inspection report for independent review.
6. In a trusted local deployment only, explicitly consent to local metadata registration and select/create a project.

A task gate indicates only whether the dataset meets the code's declared screening prerequisites. It is not a site-accuracy certificate, safety approval, forecast-performance guarantee, or authorization to issue equipment commands.

## Security and retention boundaries

- Never enable local workspace persistence on a public/shared Streamlit deployment.
- Do not upload confidential, personal, credential-bearing or operationally sensitive data to the public demo.
- The local SQLite database is not encrypted and has no authentication, authorization, multi-tenant isolation, backup/restore workflow or secure-deletion guarantee.
- The audit hash chain is tamper-evident for ordinary application use, not protection against an administrator who can edit the database file.
- Back up the local database only through an approved secure process; do not commit it to Git.
- CSV/XLSX parsing uses bounded workbook inspection; formula values are not evaluated as executable content.

## Supported data formats

CSV and XLSX are accepted. Timestamp values must be ISO-8601 with timezone offsets for CSV. Excel timestamps without timezone information require an explicit IANA timezone. Ambiguous units are not guessed; missing values are not imputed; energy and power units are not silently interchanged.
