"""示例插件：按字段去重的清洗算子。仅依赖公共 SDK。"""
from aixian.plugin_sdk import CleaningOperatorPlugin


class DedupOperator(CleaningOperatorPlugin):
    def apply(self, record: dict, params: dict) -> dict | None:
        field = params.get("field", "text")
        value = str(record.get(field, ""))
        if not params.get("case_sensitive", False):
            value = value.lower().strip()
        seen = params.setdefault("_seen", set())
        if value in seen:
            return None
        seen.add(value)
        return record
