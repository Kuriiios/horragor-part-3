Security
========

Authentication flow
-------------------

Passwords are never stored directly. An Argon2id hash is supplied through
``HORRAGOR_AUTH_PASSWORD_HASH``. Successful login issues an HS256 access token
with a short lifetime and a refresh token with a unique ID. Refresh tokens are
stored only as SHA-256 hashes in SQLite, consumed atomically, and rotated on
every refresh. Reuse of a consumed token is rejected.

.. mermaid::

   sequenceDiagram
       participant U as Streamlit
       participant A as Intelligence API
       participant R as Refresh store
       U->>A: POST /auth/login (TLS)
       A-->>U: access + refresh
       U->>A: POST /chat (Bearer access)
       A-->>U: answer
       U->>A: POST /auth/refresh (one-time refresh)
       A->>R: atomically consume hash
       R-->>A: consumed
       A-->>U: rotated access + refresh

Generate deployment values locally:

.. code-block:: powershell

   uv run python -m src.auth.cli generate-secret
   uv run python -m src.auth.cli hash-password

Keep the Argon2 hash single-quoted in ``.env`` so its dollar signs remain
literal. Production startup fails closed if authentication is enabled without
a username, password hash, or signing secret.

Transport and service isolation
-------------------------------

Compose creates a private CA and an intelligence API certificate in separate
volumes. The UI and Prometheus mount only the CA; only the intelligence API
mounts the private key. The UI refuses to send login credentials over remote
plain HTTP. Data API calls use an independent service key and a network that is
unreachable from the UI or host.

Secrets
-------

``.env``, ``.ENV``, refresh databases, logs, and generated reports are ignored.
Never commit service-role Supabase keys, JWT secrets, passwords, or Langfuse
keys. Rotate a credential immediately if it enters a commit, trace, screenshot,
or issue. Compose sources the HorRAGor service key, signing secret, and Argon2
hash as Docker secrets and mounts them under ``/run/secrets``; container
inspection exposes only file paths. Direct environment variables remain
available for local development and take precedence over ``*_FILE`` settings.
Use a managed secret store for non-local deployments.

The intelligence API buffers at most ``HORRAGOR_MAX_REQUEST_BODY_BYTES`` before
Pydantic validation (128 KiB by default), preventing oversized JSON bodies from
exhausting application memory. The private data client retries only idempotent
GET requests for transient connection, 502, 503, and 504 failures.

Data minimization
-----------------

Langfuse receives the current user question and final answer plus bounded
operational metadata. It does not receive API keys or raw configuration. The
movie database contains only public work metadata and professional credits.
Refresh tokens are hashed and conversation history remains ephemeral in the UI
session.
