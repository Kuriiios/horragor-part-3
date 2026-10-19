API Reference
=============

Interactive OpenAPI documentation is available at ``/docs`` on each FastAPI
service and the machine-readable contracts at ``/openapi.json``.

Intelligence API
----------------

``POST /auth/login`` issues a short-lived access token and one-time refresh
token. ``POST /auth/refresh`` rotates the refresh token. ``POST /auth/logout``
revokes it. ``POST /chat`` and ``GET /movies/search`` require bearer
authentication when ``HORRAGOR_AUTH_ENABLED`` is true. ``GET /health`` and
``GET /metrics`` remain public inside their private networks for orchestration.

.. automodule:: src.API.api_schemas
   :members:
   :undoc-members:

.. automodule:: src.API.main_api
   :members: login, refresh_access_token, logout, search_movies, process_chat_message, health_check

Private data API
----------------

The data API is not host-published. Its ``/v1`` routes optionally require
``X-Internal-API-Key`` and expose only fixed operations: stats, bounded search,
one movie by ID, and synopsis-only neighbors. It accepts no SQL or arbitrary
filter expression.

.. automodule:: src.data_api.schemas
   :members:
   :undoc-members:

.. automodule:: src.data_api.main
   :members: store_stats, search_movies, get_movie, similar_movies, health_check

Presentation client
-------------------

.. automodule:: src.ui.api_client
   :members:
   :undoc-members:
