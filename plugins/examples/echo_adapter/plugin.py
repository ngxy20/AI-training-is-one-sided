"""示例插件：规则式模型适配器，用于无网络环境下的评测链路演示。

真实项目可在此接入私有推理网关、内部模型 SDK 或自定义鉴权逻辑。
"""
from aixian.plugin_sdk import ModelAdapterPlugin, ModelCase


class RuleAdapter(ModelAdapterPlugin):
    def generate(self, case: ModelCase, config: dict) -> str:
        rules = config.get("rules") or {}
        prefix = str(config.get("prefix") or "")
        prompt = (case.input or "").strip()
        if prompt in rules:
            return prefix + str(rules[prompt])
        for key, value in rules.items():
            if str(key) and str(key) in prompt:
                return prefix + str(value)
        return prefix + prompt
