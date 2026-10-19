Data Architecture
=================

Conceptual data model (MCD)
---------------------------

A movie may originate from several sources, have several genres, and contain
cast or crew credits. Personal data is limited to public professional credit
names and source identifiers; HorRAGor stores no viewer profile or conversation
content in the movie database.

.. mermaid::

   erDiagram
       MOVIE ||--o{ MOVIE_SOURCE : has_provenance
       SOURCE ||--o{ MOVIE_SOURCE : supplies
       MOVIE ||--o{ MOVIE_GENRE : classified_as
       GENRE ||--o{ MOVIE_GENRE : labels
       MOVIE ||--o{ CREDIT : has
       PERSON ||--o{ CREDIT : receives
       MOVIE {
           text id PK
           text tmdb_id UK
           text imdb_id UK
           text title
           date release_date
           text overview
           vector overview_embedding
       }
       SOURCE { text name PK }
       GENRE { text name PK }
       PERSON { text id PK text name }
       CREDIT { text id PK text credit_type text role_name }

Logical data model (MLD)
------------------------

* ``movies(id, tmdb_id, imdb_id, title, normalized_title, release_date, ...,
  overview_embedding)``
* ``sources(name)``
* ``movie_sources(movie_id, source_name, source_record_id, payload)``
* ``genres(name)``
* ``movie_genres(movie_id, genre_name)``
* ``people(id, name)``
* ``credits(id, movie_id, person_id, credit_type, role_name, billing_order)``

Composite primary keys on the association tables prevent duplicate provenance
and genres. Credit identity is unique by movie, person, credit type, and role.
TMDB and IMDb identifiers are independently unique.

Physical data model (MPD)
-------------------------

``migrations/001_initial.sql`` is the PostgreSQL/Supabase physical definition.
It enables pgvector, creates an HNSW cosine index over 768-dimensional synopsis
vectors, validates score ranges, uses 64-bit monetary columns, enables row-level
security, and revokes table access from ``anon`` and ``authenticated`` roles.
Only the backend service role performs ingestion.

The SQLAlchemy mapping lives in ``src.persistence.models``:

.. autoclass:: src.persistence.models.Movie

.. autoclass:: src.persistence.models.Source

.. autoclass:: src.persistence.models.MovieSource

.. autoclass:: src.persistence.models.Genre

.. autoclass:: src.persistence.models.MovieGenre

.. autoclass:: src.persistence.models.Person

.. autoclass:: src.persistence.models.Credit

FAISS runtime schema
--------------------

The private data service persists ``movies.index`` for vectors, ``movies.json``
for rows aligned to numeric labels, and ``manifest.json`` for format, source
size, timestamp, dimension, and record count. Rebuilds write temporary files
and atomically replace each artifact. The gold CSV remains the rebuild source.
