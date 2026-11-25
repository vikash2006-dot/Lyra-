"""Safe, repeatable migration of pre-separation LYRA data into backend/storage.

Before the frontend/backend split, LYRA kept its SQLite databases and ``.env`` in the
project root (relative to the working directory). The backend now owns all data under
``backend/storage/data`` and reads configuration from ``backend/.env``.

For each legacy database the migration:
  1. Skips it if the target already exists (repeatable / idempotent).
  2. Copies it with SQLite's online backup API (consistent even if open elsewhere).
  3. Verifies every table's row count matches between source and copy.
  4. Moves the original into ``backend/storage/backups/<timestamp>/`` (never deleted).

``.env`` is copied to ``backend/.env`` (if absent) and the original moved to the backup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

from lyra.observability.logging import get_logger

logger = get_logger("api.migration")

LEGACY_DATABASES = ("lyra_memory.db", "lyra_learning.db", "lyra_auth.db", "lyra_automation.db")


@dataclass
class MigrationReport:
    migrated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    backup_dir: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.migrated)


def _table_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


def _copy_sqlite(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".migrating")
    if tmp.exists():
        tmp.unlink()
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    target = sqlite3.connect(tmp)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    tmp.replace(dst)


def migrate_legacy_data(project_root: Path, backend_dir: Path, data_dir: Path) -> MigrationReport:
    report = MigrationReport()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = backend_dir / "storage" / "backups" / f"pre-separation-{stamp}"

    def _backup(path: Path) -> None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(backup_dir / path.name))
        report.backup_dir = str(backup_dir)

    for name in LEGACY_DATABASES:
        src = project_root / name
        dst = data_dir / name
        if not src.exists():
            continue
        if dst.exists():
            report.skipped.append(name)
            continue
        try:
            before = _table_counts(src)
            _copy_sqlite(src, dst)
            after = _table_counts(dst)
            if before != after:
                dst.unlink(missing_ok=True)
                raise RuntimeError(f"row counts differ after copy: {before} != {after}")
            _backup(src)
            report.migrated.append(name)
            logger.info("Migrated %s -> %s (%d tables verified)", src, dst, len(after))
        except Exception as err:  # keep the original in place on any failure
            report.failed.append(f"{name}: {err}")
            logger.error("Failed to migrate %s: %s", name, err)

    legacy_env = project_root / ".env"
    backend_env = backend_dir / ".env"
    if legacy_env.exists() and not backend_env.exists():
        shutil.copy2(legacy_env, backend_env)
        _backup(legacy_env)
        report.migrated.append(".env")
        logger.info("Moved project .env to %s", backend_env)

    return report
