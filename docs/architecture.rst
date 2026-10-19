System Architecture
===================

Runtime topology
----------------

The production topology enforces three ownership boundaries. Streamlit owns
presentation only, the intelligence API owns authentication and LangGraph, and
the data API alone mounts the CSV and FAISS artifacts. No data service port is
published to the host.

.. mermaid::

   flowchart LR
       Browser[Browser] -->|HTTP localhost only| UI[Streamlit UI]
       UI -->|HTTPS + bearer token| AI[Intelligence API]
       AI -->|HTTP + service key\nprivate data plane| DATA[Private Data API]
       DATA --> CSV[(Gold CSV)]
       DATA --> FAISS[(FAISS index)]
       AI -->|OpenAI-compatible API| MODEL[Optional OpenVINO model]
       AI -->|traces| LF[Langfuse]
       PROM[Prometheus] --> AI
       PROM --> DATA
       GRAFANA[Grafana] --> PROM
       KUMA[Uptime Kuma] --> UI
       KUMA --> AI
       KUMA --> DATA

Network policy
--------------

``data-plane`` contains only the data and intelligence APIs. The data service
has no egress network and no host binding. ``presentation-plane`` contains the
UI and intelligence API. ``model-plane`` isolates the optional local model.
``observability`` contains metrics consumers and monitored services.
``langfuse-internal`` isolates Langfuse data stores. Only the intelligence API
and Langfuse workers join the egress network for Wikipedia and required
external calls.

Data flow
---------

1. Source adapters produce normalized ``MovieRecord`` values.
2. Reconciliation applies TMDB, Rotten Tomatoes, Kaggle, IMDb, and Spark source
   priority and publishes the gold CSV atomically.
3. The data service owns the FAISS index and serves bounded typed operations.
4. The intelligence service resolves a movie, executes the peer-to-peer graph,
   and returns a Pydantic response.
5. Streamlit stores only bounded conversation turns and credentials in its
   server-side session.
