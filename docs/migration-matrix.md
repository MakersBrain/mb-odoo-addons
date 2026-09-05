# Candidate migration matrix

This matrix is enforced by `tools/check_migration_matrix.py`. Installed versions
refer to the pinned predecessor fixture; target versions are the candidate manifests.

| Add-on | Installed | Target | Migration / phase | Observable postcondition |
|---|---:|---:|---|---|
| `l10n_fr_micro_urssaf` | 19.0.2.0.1 | 19.0.2.0.2 | `19.0.2.0.2/pre-migrate.py` | Dated-rule preflights pass; invariant lock rows exist. |
| `mb_ceramics_firing` | 19.0.3.0.1 | 19.0.3.0.3 | `19.0.3.0.3/pre-migrate.py` | Kiln occupancy preflight passes. |
| `mb_commercial_operations_depot` | 19.0.2.1.0 | 19.0.2.1.2 | `19.0.2.1.2/pre-migrate.py` | Active depot-contract overlap preflight passes. |
| `mb_commercial_operations_stock` | 19.0.2.0.1 | 19.0.2.0.2 | `19.0.2.0.2/pre-migrate.py` | Duplicate-lot preflight passes; unique key exists. |
| `mb_invoice_capture` | 19.0.1.5.3 | 19.0.1.5.5 | `19.0.1.5.5/post-migrate.py` | Stored supplier matching keys are populated. |
| `mb_label` | 19.0.1.2.2 | 19.0.1.2.5 | `19.0.1.2.4/pre-migrate.py` | Active-default duplicate preflight passes. |
| `mb_label` | 19.0.1.2.2 | 19.0.1.2.5 | `19.0.1.2.5/post-migrate.py` | Company seeds exist; predecessor-selected v99 remains current. |
| `mb_webshop` | 19.0.1.5.2 | 19.0.1.6.0 | `19.0.1.6.0/pre-migrate.py` | Legacy holds receive the order's required company. |

Transactional migrations use normal index/constraint creation. No migration uses
`CREATE INDEX CONCURRENTLY`; adopting an online index later requires a separately
rehearsed maintenance operation because Odoo upgrades run inside a transaction.
