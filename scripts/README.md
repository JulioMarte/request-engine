# Repository scripts

Scripts are thin developer/operations entrypoints, not a second implementation layer.

- `db/apply_design_chain.sh` applies the current pre-baseline PostgreSQL design chain to the database selected by standard `PG*` environment variables.

Business logic must not migrate into shell scripts. Reusable application behavior belongs to the owning Python module.
