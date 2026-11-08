"""示例插件：报告渲染器，返回 HTML 字符串。"""
from html import escape

from aixian.plugin_sdk import ReportContext, ReportRendererPlugin


class MinimalHtmlRenderer(ReportRendererPlugin):
    def render(self, report: ReportContext) -> str:
        rows = "".join(
            "<li>{}: {}</li>".format(escape(str(e.get("type"))), escape(str(e.get("id"))))
            for e in report.linked_entities)
        return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                "<h1>{}</h1><h2>关联实体</h2><ul>{}</ul></html>").format(
                    escape(report.report.get("name", "报告")), rows)
