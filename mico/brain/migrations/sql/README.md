# Production migrations

Numbered `.sql` files for the real `mico` schema (Track, Run, Revision,
Ledger, etc.) land here, named `<NNNN>_<description>.sql` per
`mico/brain/migrations/runner.py`.

This directory is intentionally empty as of M1.7 (the migration *runner*).
The actual schema is owned by M1.8 (`MetadataStore` SQLite implementation) —
see `docs/mico-implementation-design.md`.
