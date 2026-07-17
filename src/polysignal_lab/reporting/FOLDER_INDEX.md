## 📁 reporting/

**Architecture**:
- Read-only reporting projections

**Files**:
- `daily_report.py` - Builds daily reports from native event projections
- `aggregates.py` - Computes reporting aggregates
- `rejections.py` - Normalizes native rejection reasons
- `strategy_stats.py` - Builds strategy leaderboard rows
- `exit_result.py` - Builds immutable exit result projections
- `__init__.py` - Reporting package exports

🔄 **Self-reference**: When files in this folder change, update this index and PROJECT_INDEX.md
