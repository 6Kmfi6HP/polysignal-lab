## 📁 app/

**Architecture**:
- Application code

**Files**:
- `scheduler_shared.py` - Application code
- `reporting_storage.py` - Exports report result storage operations
- `reporting_types.py` - Defines daily report inputs, including telemetry completeness reasons
- `reporting_sources.py` - Collects creation-day durable order state, native fills, and explicit projection loss
- `reporting_equity.py` - Exports report equity inputs
- `reporting_build.py` - Builds reports with explicit telemetry completeness
- `reporting.py` - Exports generate_daily_report and 1 more
- `scheduler_health.py` - Persists runtime health through the retention-aware service boundary
- `readonly_smoke_types.py` - Exports ReadonlySmokeRequest and 9 more
- `readonly_smoke.py` - Exports collect_readonly_smoke and write_evidence
- `readonly_smoke_public.py` - Exports make_public_client and 11 more
- `readonly_smoke.py` - Exports collect_readonly_smoke and 1 more
- `main.py` - Exports build_parser and 7 more
- `__init__.py` - Application code

🔄 **Self-reference**: When files in this folder change, update this index and PROJECT_INDEX.md
