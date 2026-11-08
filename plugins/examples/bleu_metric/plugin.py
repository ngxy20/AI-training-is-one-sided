"""示例插件：基于 unigram 精确率的 BLEU 近似指标（无第三方依赖）。"""
from aixian.plugin_sdk import EvalCase, EvalMetricPlugin, MetricResult


class BleuMetric(EvalMetricPlugin):
    def score(self, case: EvalCase, output: str) -> MetricResult:
        expected = (case.expected or "").split()
        predicted = (output or "").split()
        if not expected or not predicted:
            value = 1.0 if expected == predicted else 0.0
        else:
            hits = sum(1 for token in predicted if token in expected)
            precision = hits / len(predicted)
            recall = hits / len(expected)
            value = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        threshold = float(case.metadata.get("threshold", 0.5))
        return MetricResult(name="bleu_like", value=round(value, 4), passed=value >= threshold,
                            detail={"expected": case.expected, "output": output})
