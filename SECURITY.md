# Security policy

## Scope and safety boundary

islandOS is an early-stage research prototype. It is not a production service or a safety-certified controller, and it must not be connected directly to PLCs, actuators, or other operational control paths. Do not include secrets, credentials, personal data, or restricted site measurements in public issues or pull requests.

## Reporting a vulnerability

If GitHub's private vulnerability reporting is enabled for this repository, use the repository **Security** tab and choose **Report a vulnerability**. If private reporting is not available, contact the repository maintainer through a verified private channel and ask for a secure reporting route; do not publish exploit details or sensitive logs in a public issue.

Include, where safe:

- The affected commit or release.
- A concise description of the security impact and affected component.
- Minimal reproduction steps that do not expose credentials or real site data.
- Any mitigations already identified.

Please allow the maintainer time to assess and coordinate a fix before public disclosure. This project has no guaranteed response SLA or production support commitment.

## Existing checks and known gaps

Pull requests run the configured regression and packaging workflows. The Python dependency audit checks resolved requirements, and Dependabot proposes dependency and GitHub Actions updates. These checks are not a substitute for container-image scanning, a reviewed lockfile, signed release artifacts, authentication/authorization, TLS, incident response, or a site-specific security review. The dependency-audit workflow now retains CycloneDX JSON audit/SBOM artifacts for each Python requirements lock for 30 days; these describe Python dependencies, not the complete container image or OS packages. An immutable base-image digest is now pinned and Dependabot proposes weekly Docker updates. The container smoke workflow is being extended to retain a CycloneDX SBOM for the built image; image signing and production access/network controls remain open gaps. The deployment runbook lists the outstanding production controls.
