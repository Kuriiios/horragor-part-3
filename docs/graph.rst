LangGraph Cartography
=====================

HorRAGor deliberately has no manager agent. Each worker receives the shared
``AgentState`` and returns only its state updates.

.. mermaid::

   stateDiagram-v2
       [*] --> RAG
       RAG --> Narration: local evidence sufficient
       RAG --> Scraper: weak evidence or detailed synopsis tool
       Scraper --> Narration: bounded web evidence
       Narration --> [*]

RAG worker
----------

The RAG worker is the first contact. It resolves explicit and historical movie
references, queries only the bounded data gateway, plans against exactly five
safe tools, and binds model-proposed arguments back to canonical IDs and known
values. It never accepts SQL from a model.

Router
------

``should_scrape_or_narrate`` is a pure decision function. Out-of-scope
questions and sufficient local evidence route directly to narration. Missing
evidence or the sole web tool routes to the scraper.

Scraper worker
--------------

The scraper performs bounded Wikipedia requests. A detailed synopsis request
must resolve to a page matching the requested film. Generic local misses use a
small web search before narration.

Narration worker
----------------

The narrator receives clipped evidence, not retrieval plumbing or prior model
logs. It uses the local OpenAI-compatible endpoint when available and otherwise
returns an explicit evidence-only fallback.

State contract
--------------

.. automodule:: src.models.state
   :members:
   :undoc-members:

Graph implementation
--------------------

.. automodule:: src.graph.pipeline
   :members:

.. automodule:: src.graph.router
   :members:

.. automodule:: src.graph.tools_nodes
   :members: rag_node, scraper_node, narration_node
