# Public Streamlit deployment check

The Streamlit Cloud visibility setting is managed by the deployment owner in Streamlit Community Cloud; it is not controlled by this Git repository or by `.streamlit/config.toml`.

## Symptom

The hosted-health workflow probes both `/` and `/_stcore/health`. A redirect (HTTP 303) to `share.streamlit.io/-/auth/app` means an unauthenticated visitor is being sent to Streamlit sign-in. This is an access/hosting configuration result, not a Python unit-test failure.

## Restore intended public access

1. Sign in to the Streamlit Community Cloud account that owns the IslandOS deployment.
2. Open the IslandOS app's settings / sharing controls.
3. Set the app visibility to public (available to anyone with the link), if that is the intended release mode.
4. Save the setting, then open `https://islandos.streamlit.app/` in a private/incognito browser window without signing in.
5. Confirm the landing page loads and the app health endpoint returns its expected healthy response. Re-run the GitHub Actions hosted-health workflow.

If the app owner cannot change visibility, check deployment ownership and workspace policy. Do not add credentials, tokens, or authentication bypasses to the repository to work around this setting.

## Evidence boundary

A successful GitHub code build does not prove that Streamlit Cloud is publicly accessible. Keep hosted availability separate from unit-test and container-smoke-test status.
