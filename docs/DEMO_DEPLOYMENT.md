# Publish the IslandOS interactive demo

The repository contains a Streamlit dashboard at `app.py`. It is not publicly hosted by this repository automatically. To make it accessible to reviewers, deploy it through Streamlit Community Cloud (the hosting account and deployment approval must be completed by a team member).

## Before publishing

1. Confirm the `nan-ao-scenario-pilot` branch has the latest `app.py`, `requirements.txt`, and README.
2. Check the dashboard locally with `python -m pip install -r requirements.txt` and `streamlit run app.py`.
3. Test default, low-renewable, high-renewable, and backup-enabled cases.
4. Verify the page clearly says that the inputs are synthetic and the model is not a field-validated controller.
5. Do not publish claims of real Nan'ao measurements, verified cost savings, avoided emissions, or field deployment.

## Streamlit Community Cloud setup

1. Sign in to Streamlit Community Cloud using the team's chosen account.
2. Create a new app and connect the GitHub repository `HaochuanLin/islandOS`.
3. Select branch `nan-ao-scenario-pilot`.
4. Set the main file path to `app.py`.
5. Deploy, wait for the build to finish, and open the generated public app URL.
6. Test the public URL in a private/incognito browser and on a phone. Confirm that the charts render and parameter controls work.
7. Add the public demo URL to the submission form only after this smoke test passes.

## If deployment fails

- Read the build log; do not randomly change dependencies.
- Confirm Python version compatibility with the repository's dependencies.
- Run `python -m compileall -q app.py island_microgrid_ro_sim.py` and `python -m unittest discover -s tests -v`.
- If the hosting service is unavailable, submit the repository link plus the exact local run command and a short recorded walkthrough, clearly labelled as a local demonstration.

## Public-demo limitation

The current dashboard wraps the existing 24-hour synthetic simulator. It is an interactive research demonstration, not a calibrated digital twin, real-time data connection, or operational control system.
