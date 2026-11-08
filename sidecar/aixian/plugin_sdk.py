"""Public plugin SDK v0.1. This module is the ONLY stable contract for extensions.

Main application is MIT-licensed; plugin authors depend on this file only.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

SDK_VERSION = "0.1"

EXTENSION_POINTS = (
    "data_source",
    "cleaning_operator",
    "annotation_template",
    "training_backend",
    "eval_metric",
    "model_adapter",
    "report_renderer",
    "command",
)

PERMISSIONS = (
    "datasource:connect",
    "network:outbound",
    "fs:read",
    "fs:write",
    "job:submit",
    "training:submit",
    "model:invoke",
)

HIGH_RISK_PERMISSIONS = frozenset({
    "network:outbound", "fs:write", "job:submit", "training:submit", "model:invoke",
})


@dataclass
class ModelCase:
    """A single inference request passed to a model adapter plugin."""
    id: str = ""
    input: str = ""
    expected: str | None = None
    category: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TableSchema:
    name: str
    columns: list[dict[str, Any]] = field(default_factory=list)
    row_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    row_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobContext:
    job_id: str
    project_id: str
    workdir: str
    command: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    log_path: str = ""
    log: Callable[[str], None] | None = None


@dataclass
class JobStatus:
    state: str  # queued/running/succeeded/failed/cancelled
    detail: str = ""
    progress: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalCase:
    id: str
    input: str
    expected: str | None = None
    category: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricResult:
    name: str
    value: float
    passed: bool | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReportContext:
    report: dict[str, Any]
    sections: list[dict[str, Any]] = field(default_factory=list)
    linked_entities: list[dict[str, Any]] = field(default_factory=list)


class DataSourcePlugin(ABC):
    @abstractmethod
    def test_connection(self, config: dict[str, Any]) -> bool: ...

    @abstractmethod
    def list_schema(self, config: dict[str, Any]) -> list[TableSchema]: ...

    @abstractmethod
    def query(self, config: dict[str, Any], sql: str) -> QueryResult: ...


class CleaningOperatorPlugin(ABC):
    @abstractmethod
    def apply(self, record: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | None: ...


class TrainingBackendPlugin(ABC):
    @abstractmethod
    def submit(self, job: JobContext) -> str: ...

    @abstractmethod
    def status(self, job_id: str) -> JobStatus: ...

    @abstractmethod
    def logs(self, job_id: str) -> Iterable[str]: ...


class EvalMetricPlugin(ABC):
    @abstractmethod
    def score(self, case: EvalCase, output: str) -> MetricResult: ...


class ModelAdapterPlugin(ABC):
    """Turns a prompt/case into a model output. Used by EvalRun / ABTest / LLM-as-judge."""

    @abstractmethod
    def generate(self, case: ModelCase, config: dict[str, Any]) -> str: ...


class ReportRendererPlugin(ABC):
    @abstractmethod
    def render(self, report: ReportContext) -> str: ...  # returns HTML


class AnnotationTemplatePlugin(ABC):
    @abstractmethod
    def schema(self) -> dict[str, Any]: ...

    @abstractmethod
    def validate(self, label: dict[str, Any], schema: dict[str, Any]) -> bool: ...


class CommandPlugin(ABC):
    @abstractmethod
    def run(self, payload: dict[str, Any], context: JobContext) -> dict[str, Any]: ...


EXTENSION_BASES: dict[str, type] = {
    "data_source": DataSourcePlugin,
    "cleaning_operator": CleaningOperatorPlugin,
    "training_backend": TrainingBackendPlugin,
    "eval_metric": EvalMetricPlugin,
    "model_adapter": ModelAdapterPlugin,
    "report_renderer": ReportRendererPlugin,
    "annotation_template": AnnotationTemplatePlugin,
    "command": CommandPlugin,
}

# V2 frontend protocol: message shapes are defined now, transport is not implemented.
FRONTEND_EVENT = {"type": "plugin.event", "version": "0.1", "event": "string", "payload": "object"}
FRONTEND_COMPONENT = {"type": "plugin.component", "version": "0.1", "slot": "string", "schema": "object"}


def validate_manifest(manifest: dict[str, Any], app_version: str) -> list[str]:
    """Return a list of problems; empty list means the manifest is loadable."""
    from . import config

    problems: list[str] = []
    required = ("id", "name", "version", "sdk_version", "extension_points")
    for key in required:
        if not manifest.get(key):
            problems.append(f"manifest 缺少字段 {key}")
    if manifest.get("sdk_version") != config.SDK_VERSION:
        problems.append(
            f"SDK 版本不兼容: 插件 {manifest.get('sdk_version')} / 应用 {config.SDK_VERSION}"
        )
    spec = manifest.get("app_version", "")
    if spec and not _version_matches(app_version, str(spec)):
        problems.append(f"应用版本不满足约束: {spec}")
    for perm in manifest.get("permissions", []):
        if perm not in PERMISSIONS and ":" in perm:
            problems.append(f"未知权限: {perm}")
    for point in manifest.get("extension_points", []):
        if point.get("point") not in EXTENSION_POINTS:
            problems.append(f"未知扩展点: {point.get('point')}")
    return problems


def _version_matches(version: str, spec: str) -> bool:
    import re

    for op, target in re.findall(r"(>=|<=|==|!=|>|<)?\s*(\d+\.\d+\.\d+)", spec):
        left = tuple(int(x) for x in version.split(".")[:3])
        right = tuple(int(x) for x in target.split("."))
        ok = {
            ">=": left >= right, "<=": left <= right, "==": left == right,
            "!=": left != right, ">": left > right, "<": left < right, "": left == right,
        }[op or ""]
        if not ok:
            return False
    return True
