"""Plugin discovery / loading / permission enforcement.

Sources, in order: user plugin dir (~/.aixian/plugins), bundled examples,
Python entry points in group ``aixian.plugins``.
MVP loads in-process; V2 adds subprocess isolation + signature verification.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config
from .errors import ApiError
from .plugin_sdk import (
    EXTENSION_BASES,
    HIGH_RISK_PERMISSIONS,
    validate_manifest,
)


@dataclass
class DiscoveredPlugin:
    id: str
    name: str
    version: str
    sdk_version: str
    app_version: str
    permissions: list[str]
    extension_points: list[dict[str, str]]
    config_schema: dict[str, Any]
    path: Path | None
    manifest: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def summary(self, enabled: bool = False) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "sdk_version": self.sdk_version,
            "app_version": self.app_version,
            "permissions": self.permissions,
            "extension_points": self.extension_points,
            "config_schema": self.config_schema,
            "path": str(self.path) if self.path else "entry-point",
            "problems": self.problems,
            "high_risk": bool(HIGH_RISK_PERMISSIONS.intersection(self.permissions)),
            "enabled": enabled,
        }


class PluginRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, Any] = {}
        self._instances: dict[str, Any] = {}

    def discover(self) -> list[DiscoveredPlugin]:
        found: list[DiscoveredPlugin] = []
        roots = [config.EXTERNAL_PLUGINS_DIR, config.BUNDLED_PLUGINS_DIR]
        for root in roots:
            if not root.exists():
                continue
            for child in sorted(root.iterdir()):
                manifest_file = child / "manifest.json" if child.is_dir() else child
                if manifest_file.name == "manifest.json" and manifest_file.exists():
                    found.append(self._read_manifest(manifest_file, manifest_file.parent))
        found.extend(self._entry_points())
        unique: dict[str, DiscoveredPlugin] = {}
        for item in found:
            unique.setdefault(item.id, item)
        return list(unique.values())

    def _read_manifest(self, path: Path, base: Path) -> DiscoveredPlugin:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raw = {"id": base.name, "name": base.name, "version": "0.0.0", "sdk_version": "?",
                   "extension_points": []}
            problems = [f"manifest.json 解析失败: {exc}"]
        else:
            problems = validate_manifest(raw, config.app_version())
        return DiscoveredPlugin(
            id=raw.get("id", base.name),
            name=raw.get("name", base.name),
            version=raw.get("version", "0.0.0"),
            sdk_version=raw.get("sdk_version", "?"),
            app_version=raw.get("app_version", "*"),
            permissions=list(raw.get("permissions", [])),
            extension_points=list(raw.get("extension_points", [])),
            config_schema=dict(raw.get("config_schema", {})),
            path=base,
            manifest=raw,
            problems=problems,
        )

    def _entry_points(self) -> list[DiscoveredPlugin]:
        result: list[DiscoveredPlugin] = []
        try:
            points = importlib.metadata.entry_points(group="aixian.plugins")
        except Exception:
            return result
        for ep in points:
            try:
                obj = ep.load()
                raw = obj.get("manifest", obj) if isinstance(obj, dict) else getattr(obj, "manifest", {})
                raw = dict(raw)
                raw.setdefault("id", ep.value)
                raw.setdefault("name", ep.name)
                item = DiscoveredPlugin(
                    id=raw.get("id", ep.name),
                    name=raw.get("name", ep.name),
                    version=raw.get("version", "0.0.0"),
                    sdk_version=raw.get("sdk_version", "?"),
                    app_version=raw.get("app_version", "*"),
                    permissions=list(raw.get("permissions", [])),
                    extension_points=list(raw.get("extension_points", [])),
                    config_schema=dict(raw.get("config_schema", {})),
                    path=None,
                    manifest=raw,
                    problems=validate_manifest(raw, config.app_version()),
                )
                result.append(item)
            except Exception as exc:  # a broken plugin must not break the host
                result.append(DiscoveredPlugin(
                    id=ep.name, name=ep.name, version="0.0.0", sdk_version="?", app_version="*",
                    permissions=[], extension_points=[], config_schema={}, path=None,
                    problems=[f"entry point 加载失败: {exc}"],
                ))
        return result

    def _module(self, plugin: DiscoveredPlugin, module_name: str) -> Any:
        key = f"{plugin.id}::{module_name}"
        if key in self._modules:
            return self._modules[key]
        if plugin.path is None:
            return importlib.import_module(module_name)
        rel = module_name.replace(".", "/")
        path = plugin.path / f"{rel}.py"
        if not path.exists():
            path = plugin.path / rel / "__init__.py"
        if not path.exists():
            raise ApiError("PLUGIN_MODULE", f"插件模块不存在: {module_name}", 500, str(path))
        unique = "aixian_ext_" + hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]
        spec = importlib.util.spec_from_file_location(unique, path)
        if spec is None or spec.loader is None:
            raise ApiError("PLUGIN_MODULE", "无法加载插件模块", 500, str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        self._modules[key] = module
        return module

    def implementation(self, plugin: DiscoveredPlugin, impl_ref: str) -> Any:
        key = f"{plugin.id}::{impl_ref}"
        if key in self._instances:
            return self._instances[key]
        if plugin.problems:
            raise ApiError("PLUGIN_INCOMPATIBLE", "插件不兼容或未通过校验", 400, plugin.problems)
        if ":" not in impl_ref:
            raise ApiError("PLUGIN_IMPL", f"扩展点 impl 格式应为 module:Class -> {impl_ref}", 500)
        module_name, class_name = impl_ref.split(":", 1)
        module = self._module(plugin, module_name)
        klass = getattr(module, class_name, None)
        if klass is None:
            raise ApiError("PLUGIN_IMPL", f"插件未导出 {class_name}", 500)
        instance = klass()
        self._instances[key] = instance
        return instance

    def implementations(self, point: str, enabled_ids: set[str] | None = None) -> list[tuple[DiscoveredPlugin, dict[str, str], Any]]:
        result = []
        for plugin in self.discover():
            if plugin.problems or (enabled_ids is not None and plugin.id not in enabled_ids):
                continue
            for extension in plugin.extension_points:
                if extension.get("point") != point:
                    continue
                try:
                    impl = self.implementation(plugin, extension.get("impl", ""))
                except ApiError:
                    continue
                result.append((plugin, extension, impl))
        return result

    def enabled_ids(self, session: Any) -> set[str]:
        from sqlalchemy import select

        from .models import Plugin

        rows = session.execute(select(Plugin).where(Plugin.enabled == 1)).scalars().all()
        return {row.plugin_id for row in rows}

    def require_permission(self, plugin: DiscoveredPlugin, permission: str) -> None:
        if permission not in plugin.permissions:
            raise ApiError(
                "PLUGIN_PERMISSION",
                f"插件 {plugin.id} 未声明权限 {permission}",
                403,
                {"declared": plugin.permissions, "required": permission},
            )


registry = PluginRegistry()
