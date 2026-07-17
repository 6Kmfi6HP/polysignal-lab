## 📁 storage/

**Architecture**:
- Application code

**Files**:
- `state_store.py` - Exports StateStore
- `sqlite_store.py` - SQLite reporting store with lifecycle-aware projections, report revisions, outbox, and telemetry pruning
- `sqlite_schema.py` - SQLite reporting schema, creation-time indexes, and validation contracts
- `event_projection.py` - Canonical sparse `report_*` event projection normalizers
- `projection_migration.py` - Backed-up one-shot legacy schema to `report_*` migration
- `jsonl_store.py` - Exports JSONLStore
- `__init__.py` - Application code

🔄 **Self-reference**: When files in this folder change, update this index and PROJECT_INDEX.md
