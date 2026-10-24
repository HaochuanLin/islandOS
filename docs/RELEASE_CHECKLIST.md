# Release and deployment checklist

## Automated release-candidate gate

The workflow `.github/workflows/release-candidate.yml` runs for version tags matching `v*` and can also be dispatched manually.

A candidate is packaged only after these gates pass:

1. Install the exact CI dependency lock and run `pip check`.
2. Compile Python sources and pass the full pytest suite.
3. Audit CI, runtime, ML, and optional deep-learning dependency specifications.
4. Build the Docker image, verify it runs as non-root, and probe the Streamlit health endpoint on loopback.
5. Archive the exact Git commit; include dependency locks, a dependency inventory, SHA-256 checksums, and a machine-readable release manifest.
6. Generate GitHub artifact provenance attestations for every file in the release bundle; the workflow grants only the required OIDC and attestations permissions.
7. Verify the source archive attestation in CI with `gh attestation verify` before uploading the bundle. Reviewers should also verify each downloaded release asset independently.
8. Upload the bundle as a 90-day artifact. A version-tag run creates a **draft** GitHub release, never an automatically published release.

A manually dispatched run from a branch produces a verification artifact named `candidate-<commit>` and does not publish a GitHub release.

## Human release checklist

Before publishing a draft:

- [ ] Review the release manifest and all CI conclusions for the exact tag/commit.
- [ ] Confirm the changelog describes the intended changes.
- [ ] Check dependency audit findings and the source archive checksums.
- [ ] Verify provenance for each downloaded release asset with `gh attestation verify <asset-path> --repo HaochuanLin/islandOS`; ensure the signer workflow and source commit match the intended release. A checksum file alone is not an authenticity guarantee.
- [ ] Verify the demo and deployment instructions against the intended hosting environment.
- [ ] Confirm secrets, backups, restore/rollback, monitoring, and incident ownership for the target deployment.
- [ ] For any field pilot, obtain site-specific engineering approval, start in read-only/shadow mode, define abort thresholds, and document the rollback procedure.
- [ ] Publish the draft only after the responsible human reviewer approves it.

## Explicit non-claims

A green release workflow verifies repository tests, dependency specifications, container startup, SHA-256 consistency, and emits GitHub artifact provenance attestations for the release bundle. It does not establish field safety, real-site forecast accuracy, hardware-in-the-loop validation, operational savings, or permission to connect to PLCs/actuators.
