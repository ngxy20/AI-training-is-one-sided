"""Optional importer: legacy TrainFlow state.json/DS-*.json -> a real project.

Usage:  python -m aixian.migration --legacy-root <dir> --name "迁移项目"
<dir> must contain data/DS-*.json and data/state.json. The legacy prototype is
not shipped with this repository. The importer creates an immutable v1 dataset
version and keeps the original files untouched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import config
from .audit import record
from .database import init_project_db, init_registry, project_session, registry_session
from .models import Dataset, Project
from .services import datasets
from .util import uid
from . import workspace


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def migrate(legacy_root: Path, name: str) -> dict[str, Any]:
    config.bootstrap()
    init_registry()
    project_id = uid()
    root = workspace.ensure_workspace(project_id)
    init_project_db(project_id)
    project = Project(id=project_id, name=name, description="由 TrainFlow 原型迁移",
                      workspace_path=str(root), status="active",
                      settings_json={"migrated_from": str(legacy_root)})
    with registry_session() as session:
        session.add(project)
        session.commit()

    imported: list[dict[str, Any]] = []
    data_dir = legacy_root / "data"
    with project_session(project_id) as session:
        for file in sorted(data_dir.glob("DS-*.json")) + sorted(data_dir.glob("test_*.json")):
            rows = _load(file, [])
            if not isinstance(rows, list) or not rows:
                continue
            ds = Dataset(id=uid(), project_id=project_id, name=file.stem,
                         description=f"从原型 {file.name} 迁移", schema_json={}, source_type="migration")
            session.add(ds)
            session.commit()
            version = datasets.create_version(
                session, project_id, ds, rows,
                changelog=f"原型迁移：{file.name}（{len(rows)} 条）", source="migration",
            )
            imported.append({"file": file.name, "dataset_id": ds.id,
                             "dataset_version_id": version.id, "record_count": len(rows)})
        state = _load(data_dir / "state.json", {})
        record(session, "project.migrate", "project", project_id,
               {"legacy_state": state, "imported": imported}, project_id)
    summary = {
        "project_id": project_id, "name": name, "workspace_path": str(root),
        "imported": imported,
        "total_records": sum(i["record_count"] for i in imported),
        "legacy_files_preserved": True,
    }
    (root / "migration-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移旧版 TrainFlow 原型数据")
    parser.add_argument("--legacy-root", default=str(config.LEGACY_ROOT))
    parser.add_argument("--name", default="迁移项目")
    args = parser.parse_args()
    print(json.dumps(migrate(Path(args.legacy_root), args.name), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
