Operations and Observability
============================

Loguru
------

Every runtime process calls ``configure_logging``. Standard-library and Uvicorn
records are intercepted into Loguru, preserving exceptions. Production emits
JSON to stderr and rotated compressed JSONL files. HTTP records carry service,
request ID, method, route, status, and latency. An incoming safe
``X-Request-ID`` is echoed; otherwise the middleware generates one.

Prometheus and Grafana
----------------------

Both APIs and the optional model expose private ``/metrics`` endpoints. Labels
use route templates and bounded enum values to prevent cardinality growth.
Metrics cover request count, failures, active requests, duration histograms,
graph routes, narration mode, model tokens, and tool outcomes. Grafana
provisions the ``HorRAGor Overview`` dashboard automatically from
``deploy/grafana``.

Uptime Kuma
-----------

After creating the first local Uptime Kuma administrator at port 3002, create
three HTTP monitors:

* ``http://data-api:8002/health`` for the private data API.
* ``https://intelligence-api:8000/health`` for the intelligence API. Import
  ``/certs/ca.crt`` or enable certificate-ignore only for this internal monitor.
* ``http://ui:8501/_stcore/health`` for Streamlit.

Use a 30-second interval and two retries. Route notifications to the team's
approved incident channel. A down or degraded monitor must create a GitHub
behavior-deviation issue after immediate triage.

Langfuse
--------

The v4 stack runs a web service and worker backed by PostgreSQL, ClickHouse,
Redis, and MinIO. Create a project at port 3000 and place its keys in the ignored
``.env`` file. Each chat turn is one ``answer-chat-question`` agent trace,
grouped by Streamlit conversation ID. Nested observations are typed as
retriever, tool, and generation. Generations record stable names, model,
parameters, output, and reported input/output tokens; tool failures record an
error output and status.

Set ``LANGFUSE_TRACING_ENABLED=false`` for tests or offline operation. The API
continues without tracing. Review trace trees for meaningful root I/O, complete
nested observations, unexpected sensitive data, token anomalies, latency, and
router decisions.

Troubleshooting
---------------

* ``503`` from chat: inspect intelligence API logs, then data/model health.
* ``401`` after refresh: the one-time refresh token was expired, revoked, or
  replayed; log in again and investigate repeated replay attempts.
* Empty FAISS results: compare ``manifest.json`` source signature with the gold
  CSV and run ``horragor-build-index``.
* Missing traces: verify both Langfuse keys, ``LANGFUSE_HOST``, and worker health.
* Prometheus TLS failure: verify the CA volume and ``server_name`` in the scrape
  configuration.
