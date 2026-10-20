# Add the SDK section to AgentShield

This patch changes only `web/index.html`. It is based on the SDK + public demo version of the site.

1. Back up `web/index.html`.
2. From the AgentShield project root, extract this ZIP (it contains `web/index.html`).
3. Start `python product_server.py` and refresh the website.
4. Scroll to **Building your own AI assistant?**. Test both Copy buttons.
5. To run the local SDK example: `python -m pip install -e .` from the repository root.

The page does not publish an SDK to PyPI or deploy the website. Replace `https://YOUR-DEMO-URL` only after deploying your site.
