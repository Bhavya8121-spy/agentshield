# AgentShield dashboard replacement

1. Back up your current `dashboard.py`.
2. Copy this `dashboard.py` into the root of your AgentShield repository.
3. Install `streamlit` and `pandas` if needed.
4. Run `streamlit run dashboard.py`.

The dashboard reads `results/*.json`; it never calls OCI or modifies the database.
