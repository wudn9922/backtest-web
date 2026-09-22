# Archived Cloud Migration Policy

The earlier Cloud Run, Firestore, GCS, Cloud Tasks, Terraform, and container-based C1 design is abandoned. It is not a production path and must not be restored except from the local-only archival backup for historical inspection.

The active architecture is documented in [the zero-cost GitHub policy](../github/ZERO_COST_ARCHITECTURE_POLICY.md): public GitHub source, standard `ubuntu-24.04` GitHub Actions, GitHub Releases, and GitHub Pages only.

Frozen strategy, analytics, canonical helper, and local-database behavior remains unchanged. Any architecture change requires a Sol High decision.
