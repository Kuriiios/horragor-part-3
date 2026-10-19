# Maintained Tool References

The former prototype in this directory imported modules that were never part of
the repository and duplicated production behavior. Use these tested sources as
the canonical references instead:

- `src/tools/brief2_tools.py`: five model-visible tool contracts.
- `src/tools/brief2_scraper.py`: bounded detailed Wikipedia retrieval.
- `src/graph/tools_nodes.py`: safe tool planning, argument binding, and execution.
- `src/data_gateway.py`: local and private-HTTP movie data boundary.
- `src/ingestion/`: Brief 1 acquisition and reconciliation pipeline.

The generated API and architecture reference is built from `docs/` with Sphinx.
