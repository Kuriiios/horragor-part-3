Testing and Quality Gates
=========================

Local checks
------------

.. code-block:: powershell

   uv sync --extra docs
   uv run ruff check src tests app_frontend.py server
   uv run mypy src server app_frontend.py --ignore-missing-imports
   $env:LANGFUSE_TRACING_ENABLED = "false"
   uv run pytest -q
   uv run sphinx-build -W --keep-going -b html docs docs/_build/html
   docker compose config --quiet

Coverage policy
---------------

Brief 3 requires at least 80 percent coverage for both APIs and the UI. CI runs
three independent gates so one component cannot hide another:

.. code-block:: powershell

   uv run pytest tests/test_auth.py tests/test_langfuse_integration.py tests/test_main_api.py --cov=src.API --cov-fail-under=80
   uv run pytest tests/test_data_api.py --cov=src.data_api --cov-fail-under=80
   uv run pytest tests/test_ui_client.py --cov=src.ui --cov=app_frontend --cov-fail-under=80

The tests cover graph routing and argument binding, retrieval failure behavior,
Wikipedia matching, rotating refresh tokens and replay rejection, private API
service keys, SQLAlchemy and Supabase persistence, source normalization and
reconciliation, Langfuse observation fields, client TLS safeguards, and
Streamlit interactions through ``AppTest``.

Test isolation
--------------

Tests set ``LANGFUSE_TRACING_ENABLED=false`` and mock all web/model calls. API
configuration is patched explicitly so ambient developer credentials cannot
change expected status codes. Temporary SQLite databases are closed before
cleanup to remain reliable on Windows.
