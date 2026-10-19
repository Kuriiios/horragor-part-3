Docker Deployment
=================

Prerequisites
-------------

Use Docker Desktop with Compose v2 and at least 4 CPU cores and 16 GiB RAM when
running the complete Langfuse v4 stack. The optional local model needs
additional memory and mounts the repository's ``models`` directory read-only.

Configuration
-------------

Copy ``.env.example`` to the ignored ``.env`` file and replace every placeholder
with a distinct random value. Generate application secrets with
``python -m src.auth.cli generate-secret`` and the password hash with
``python -m src.auth.cli hash-password``. Langfuse's encryption key must be 64
hexadecimal characters. Compose converts the HorRAGor application values into
mounted Docker secrets; they do not appear in container environment inspection.

Validate before startup:

.. code-block:: powershell

   docker compose config --quiet

Startup
-------

Start the application, dashboards, Uptime Kuma, and Langfuse:

.. code-block:: powershell

   docker compose up --build -d

Enable the resource-intensive local OpenVINO model explicitly:

.. code-block:: powershell

   docker compose --profile local-model up --build -d

The user-facing UI is ``http://127.0.0.1:8501``. Langfuse is at port 3000,
Grafana at 3001, Uptime Kuma at 3002, and Prometheus at 9090. All are bound to
loopback. The two APIs have no host port; the UI reaches the intelligence API
over internal TLS and the intelligence API alone reaches the data API.

Health and shutdown
-------------------

.. code-block:: powershell

   docker compose ps
   docker compose logs --tail 100 intelligence-api data-api ui
   docker compose down

Do not add ``--volumes`` unless deleting refresh sessions, dashboards, traces,
and monitoring history is intentional. To rotate the private CA, stop the
stack and explicitly remove only the ``app-tls-ca`` and ``app-tls-server``
volumes before restarting.

Production edge
---------------

Compose binds Streamlit to loopback for local use. A remote deployment must put
a trusted HTTPS reverse proxy or load balancer in front of Streamlit, restrict
ports 3000-3002 and 9090 to administrators, and move secrets to a managed secret
store. The self-hosted Langfuse Compose topology is single-instance and is not
a high-availability design.
