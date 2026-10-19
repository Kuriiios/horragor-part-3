## Requirement

Link the brief requirement and issue addressed by this change.

## Change

Describe behavior and ownership boundaries changed.

## Risk and rollback

List security, data, performance, compatibility, and deployment risks. State the rollback path.

## Validation

- [ ] `uv run ruff check src tests app_frontend.py server`
- [ ] `uv run pytest -q`
- [ ] Relevant component coverage remains at least 80%
- [ ] `uv run sphinx-build -E -W --keep-going -b html docs docs/_build/html`
- [ ] `docker compose config --quiet` for infrastructure changes
- [ ] No credential, personal data, model binary, or generated runtime artifact is included

## Observability

Describe new or changed logs, metrics, traces, dashboards, and alerts. Include sanitized request or trace IDs when useful.
