# Deploy AgentShield on free Streamlit Community Cloud

1. Push this directory to GitHub. Never commit API keys, `.env`, or `.streamlit/secrets.toml`.
2. In Streamlit Community Cloud, choose `streamlit_app.py` as the main file.
3. Select Python 3.11 or 3.12, then deploy.
4. The mock agent requires no external model account. Live model calls require additional SDK dependencies and Streamlit Secrets.
5. The original HTML/CSS is preserved in `streamlit_frontend/index.html`. The original `/api/...` requests are bridged to Python internally; **they are not public REST endpoints**.
6. `dashboard.py` remains in the project and can be deployed as a separate Streamlit app.

This is a deployment starter. Test the page and all buttons after deployment. Do not expose live model mode without cost and abuse controls.
