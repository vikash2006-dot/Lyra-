"""Run the legacy data migration manually (it also runs automatically at backend startup).

    cd backend && python scripts/migrate_data.py
"""

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.config import BACKEND_DIR, PROJECT_ROOT, load_server_config  # noqa: E402
from app.core.migration import migrate_legacy_data  # noqa: E402

report = migrate_legacy_data(PROJECT_ROOT, BACKEND_DIR, load_server_config().data_dir)
print(f"migrated: {report.migrated or 'nothing'}")
print(f"skipped (already present): {report.skipped or 'none'}")
print(f"failed: {report.failed or 'none'}")
if report.backup_dir:
    print(f"originals backed up to: {report.backup_dir}")
sys.exit(1 if report.failed else 0)
