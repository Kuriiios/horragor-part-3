Ingestion and Reconciliation
============================

Acquisition channels
--------------------

* TMDB uses bounded ``discover/movie`` requests constrained to genre ID 27.
* Rotten Tomatoes uses headless Selenium against dynamic horror listing cards.
* Kaggle CSV files are read lazily with Polars and collected in streaming mode.
* IMDb SQLite uses a parameterized ``title_basics`` to ``title_ratings`` join,
  horror filtering, and the required ``numVotes >= 1000`` quality gate.
* PySpark joins split tab-separated IMDb basics and ratings data for large
  volumes and applies the same thematic and vote gates.

Optional dependencies are isolated in the ``ingestion`` extra. Install them
with ``uv sync --extra ingestion``. External paths and credentials remain in
environment variables and never enter Streamlit.

Normalization
-------------

All records pass through the same rules: Unicode NFC and whitespace cleanup,
HTML removal, ISO 8601 dates, January 1 for year-only dates, TMDB/IMDb ratings
on 0-10, Rotten Tomatoes percentages on 0-100, non-negative numeric fields,
and strict Horror/Gore genre filtering.

Reconciliation
--------------

Records are processed by source priority: TMDB, Rotten Tomatoes, Kaggle, IMDb,
then Spark. Identity matching uses TMDB ID first, IMDb ID second, exact title
plus year third, and fuzzy normalized title plus the same year last. Higher
priority values win; lower-priority sources fill only missing values and add
provenance.

Publication
-----------

Sources run concurrently in a bounded five-worker pool. Every source gets a
success, skipped, or failed report with latency and record count. Strict mode
fails if any configured source is unavailable. The reconciled CSV is flushed,
fsynced, and atomically replaced before optional database upsert and FAISS
rebuild.

Run the pipeline:

.. code-block:: powershell

   uv sync --extra ingestion
   uv run horragor-ingest --strict

Configuration variables include ``TMDB_BEARER_TOKEN``, ``TMDB_API_KEY``,
``KAGGLE_CSV_PATHS``, ``IMDB_SQLITE_PATH``, ``IMDB_SPARK_BASICS_PATH``,
``IMDB_SPARK_RATINGS_PATH``, ``DATABASE_URL``, ``SUPABASE_URL``, and
``SUPABASE_SERVICE_ROLE_KEY``.

.. automodule:: src.ingestion.pipeline
   :members:

.. automodule:: src.ingestion.reconciliation
   :members:

.. automodule:: src.persistence.repositories
   :members:
