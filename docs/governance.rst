Governance
==========

Issue lifecycle
---------------

Every anomaly, monitoring alert, trace deviation, security concern, and failed
quality gate must be archived as a GitHub issue. Use the behavior-deviation form
for incorrect agent output, routing, retrieval, latency, token, or monitoring
anomalies; use the bug form for deterministic software defects.

1. Record expected and observed behavior without credentials or personal data.
2. Add reproduction evidence, request/trace ID, environment, and affected
   component.
3. Assign severity and owner during triage.
4. Link the correcting pull request and its regression test.
5. Close only after CI, coverage, and relevant runtime checks pass.

Pull requests
-------------

Pull requests must identify the brief requirement, describe risk and rollback,
link issues, and include validation evidence. Changes to auth, data contracts,
network exposure, secrets, migrations, or model-visible tools require explicit
review from the owning maintainer.

Release policy
--------------

Semantic ``v*`` tags trigger signed-provenance container builds for the data,
intelligence, UI, and model images in GitHub Container Registry. CI validates
lint, tests, per-surface coverage, Sphinx, and Compose before merge. Deployment
secrets are never stored in workflow YAML or artifacts.
