"""Reports strongly linked to versions; export HTML / PDF / JSON / Markdown."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from jinja2 import Environment

from .. import workspace
from ..errors import ApiError
from ..events import hub
from ..models import Report
from ..util import as_dict, canonical, now, sha256_file, stable_hash, uid, write_json
from .common import lineage_nodes

REPORT_TYPES = ("experiment", "evaluation", "ab", "boundary", "accuracy", "custom")

_ENV = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
_HTML = _ENV.from_string("""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{{ report.name }}</title>
<style>
:root{color-scheme:light}body{font-family:"Microsoft YaHei","Segoe UI",sans-serif;margin:0;background:#f5f7fa;color:#1f2937}
.wrap{max-width:960px;margin:32px auto;background:#fff;padding:40px;border-radius:12px;box-shadow:0 2px 16px #0001}
h1{font-size:26px;margin:0 0 8px}h2{font-size:18px;margin:28px 0 12px;border-left:4px solid #4f46e5;padding-left:10px}
.meta{color:#6b7280;font-size:13px}.cards{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}
.card{flex:1;min-width:130px;background:#f3f4f6;border-radius:8px;padding:14px}
.card .k{font-size:12px;color:#6b7280}.card .v{font-size:22px;font-weight:700;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #e5e7eb;padding:8px 10px;text-align:left}
th{background:#f9fafb}tr:nth-child(even){background:#fafafa}code{background:#f3f4f6;padding:2px 5px;border-radius:4px}
footer{margin-top:36px;color:#9ca3af;font-size:12px;border-top:1px solid #eee;padding-top:12px}
</style></head><body><div class="wrap">
<h1>{{ report.name }}</h1>
<div class="meta">类型 {{ report.type }} · 生成于 {{ generated_at }} · 报告 ID {{ report.id }} · 项目 {{ project_id }}</div>
{% if summary.metrics %}<h2>核心指标</h2><div class="cards">
{% for key, value in summary.metrics.items() %}{% if value is number %}<div class="card"><div class="k">{{ key }}</div><div class="v">{{ value }}</div></div>{% endif %}{% endfor %}</div>{% endif %}
<h2>关联实体（可追溯）</h2>
<table><thead><tr><th>类型</th><th>ID</th><th>名称 / 版本</th></tr></thead><tbody>
{% for node in linked %}<tr><td>{{ node.type }}</td><td><code>{{ node.id }}</code></td><td>{{ node.label }}</td></tr>{% endfor %}
</tbody></table>
{% for section in sections %}<h2>{{ section.title }}</h2>
{% if section.table %}<table><thead><tr>{% for key in section.table[0].keys() %}<th>{{ key }}</th>{% endfor %}</tr></thead><tbody>
{% for row in section.table %}<tr>{% for key, value in row.items() %}<td>{{ value | string | truncate(160) }}</td>{% endfor %}</tr>{% endfor %}
</tbody></table>{% elif section.text %}<p>{{ section.text }}</p>{% endif %}{% endfor %}
<footer>AI Training Studio · 内容指纹 {{ fingerprint }} · 本报告强关联数据集版本 / 代码版本 / 参数 / 环境 / checkpoint</footer>
</div></body></html>""")


def validate_linked(session, linked: Any) -> list[dict[str, Any]]:
    if not isinstance(linked, list) or not linked:
        raise ApiError("ORPHAN_REPORT", "报告必须引用至少一个关联实体，禁止孤立报告", 422)
    normalized = []
    for item in linked:
        if isinstance(item, str):
            normalized.append({"type": "asset", "id": item})
        elif isinstance(item, dict) and item.get("id"):
            normalized.append({"type": item.get("type", "asset"), "id": item["id"]})
    if not normalized:
        raise ApiError("ORPHAN_REPORT", "关联实体格式无效", 422)
    resolved = lineage_nodes(session, normalized)
    if not resolved and all(item["type"] == "asset" for item in normalized):
        raise ApiError("ORPHAN_REPORT", "关联实体均无法解析", 422)
    return normalized


def build_context(session, project_id: str, report: Report) -> dict[str, Any]:
    linked = [{"type": e.get("type", "asset"), "id": e["id"], "label": e["id"]} for e in report.linked_entities_json]
    for node in lineage_nodes(session, report.linked_entities_json):
        for item in linked:
            if item["id"] == node["id"]:
                item["label"] = node["label"]
    summary = report.summary_json or {}
    sections = summary.get("sections") or []
    return {
        "report": as_dict(report),
        "project_id": project_id,
        "summary": summary,
        "sections": sections,
        "linked": linked,
        "generated_at": now().isoformat(timespec="seconds"),
        "fingerprint": stable_hash({"linked": linked, "summary": summary})[:16],
    }


def render_html(context: dict[str, Any]) -> str:
    return _HTML.render(**context)


def _render_with_plugin(session, context: dict[str, Any], plugin_id: str | None) -> str:
    if not plugin_id:
        return render_html(context)
    from ..plugin_loader import registry
    from ..plugin_sdk import ReportContext

    for plugin, _, impl in registry.implementations("report_renderer", registry.enabled_ids(session)):
        if plugin.id == plugin_id:
            return impl.render(ReportContext(
                report=context["report"], sections=context["sections"],
                linked_entities=context["linked"],
            ))
    raise ApiError("PLUGIN_NOT_FOUND", f"报告渲染插件未启用: {plugin_id}", 404)


def render_markdown(context: dict[str, Any]) -> str:
    lines = [f"# {context['report']['name']}", "",
             f"> 类型：{context['report']['type']}  ",
             f"> 生成时间：{context['generated_at']}  ",
             f"> 内容指纹：`{context['fingerprint']}`", "",
             "## 关联实体（可追溯）", "",
             "| 类型 | ID | 名称/版本 |", "| --- | --- | --- |"]
    for node in context["linked"]:
        lines.append(f"| {node['type']} | `{node['id']}` | {node['label']} |")
    metrics = context["summary"].get("metrics")
    if isinstance(metrics, dict):
        lines += ["", "## 核心指标", "", "| 指标 | 值 |", "| --- | --- |"]
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                lines.append(f"| {key} | {value} |")
    for section in context["sections"]:
        lines += ["", f"## {section.get('title', '章节')}"]
        if section.get("text"):
            lines += ["", str(section["text"])]
        table = section.get("table") or []
        if table:
            headers = list(table[0].keys())
            lines += ["", "| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
            for row in table:
                lines.append("| " + " | ".join(str(row.get(h, "")).replace("|", "\\|")[:120] for h in headers) + " |")
    lines += ["", "---", "AI Training Studio · 报告与数据版本 / 模型版本 / 评测集版本强关联"]
    return "\n".join(lines) + "\n"


def render_pdf(target: Path, context: dict[str, Any]) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        try:
            from weasyprint import HTML
            HTML(string=render_html(context)).write_pdf(str(target))
            return
        except ImportError as exc:
            raise ApiError("PDF_RENDERER_MISSING", "PDF 导出需要 reportlab 或 weasyprint", 500, str(exc)) from exc
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    font = "STSong-Light"
    title_style = ParagraphStyle("title", fontName=font, fontSize=20, leading=28, spaceAfter=10)
    h2_style = ParagraphStyle("h2", fontName=font, fontSize=14, leading=20, spaceBefore=14, spaceAfter=8)
    body_style = ParagraphStyle("body", fontName=font, fontSize=9.5, leading=14)
    doc = SimpleDocTemplate(str(target), pagesize=A4, title=context["report"]["name"],
                            leftMargin=42, rightMargin=42, topMargin=42, bottomMargin=42)
    cell = lambda text: Paragraph(xml_escape(str(text)[:200]), body_style)  # noqa: E731
    story: list[Any] = [
        Paragraph(xml_escape(context["report"]["name"]), title_style),
        Paragraph(f"类型 {context['report']['type']} · {context['generated_at']} · 指纹 {context['fingerprint']}", body_style),
        Spacer(1, 10), Paragraph("关联实体（可追溯）", h2_style),
        Table([[cell("类型"), cell("ID"), cell("名称/版本")]] +
              [[cell(n["type"]), cell(n["id"]), cell(n["label"])] for n in context["linked"]],
              colWidths=[90, 190, 210],
              style=TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6"))])),
    ]
    metrics = context["summary"].get("metrics")
    if isinstance(metrics, dict):
        numeric = [(k, v) for k, v in metrics.items() if isinstance(v, (int, float))]
        if numeric:
            story += [Paragraph("核心指标", h2_style),
                      Table([[cell("指标"), cell("值")]] + [[cell(k), cell(v)] for k, v in numeric],
                            colWidths=[240, 250],
                            style=TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db"))]))]
    for section in context["sections"]:
        story.append(Paragraph(xml_escape(section.get("title", "章节")), h2_style))
        if section.get("text"):
            story.append(Paragraph(xml_escape(section["text"]), body_style))
        table = section.get("table") or []
        if table:
            headers = list(table[0].keys())[:6]
            rows = [[cell(h) for h in headers]]
            for row in table[:60]:
                rows.append([cell(row.get(h, "")) for h in headers])
            width = (doc.width) / len(headers)
            story.append(Table(rows, colWidths=[width] * len(headers), repeatRows=1,
                               style=TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb"))])))
    doc.build(story)


def create_report(session, project_id: str, payload: dict[str, Any]) -> Report:
    linked = validate_linked(session, payload.get("linked_entities_json"))
    report_type = payload.get("type", "evaluation")
    if report_type not in REPORT_TYPES:
        raise ApiError("VALIDATION_ERROR", f"未知报告类型: {report_type}", 422, {"supported": REPORT_TYPES})
    summary = dict(payload.get("summary_json") or {})
    if payload.get("sections"):
        summary["sections"] = payload["sections"]
    root = workspace.ensure_workspace(project_id)
    report = Report(
        id=uid(), project_id=project_id, name=payload.get("name") or "未命名报告",
        type=report_type, linked_entities_json=linked, summary_json=summary,
    )
    session.add(report)
    session.flush()
    folder = root / "reports" / report.id
    folder.mkdir(parents=True, exist_ok=True)
    context = build_context(session, project_id, report)
    html_path = folder / "report.html"
    html_path.write_text(_render_with_plugin(session, context, payload.get("renderer_plugin_id")), encoding="utf-8")
    md_path = folder / "report.md"
    md_path.write_text(render_markdown(context), encoding="utf-8")
    json_path = write_json(folder / "report.json", {"context": context, "report": as_dict(report)})
    pdf_path = folder / "report.pdf"
    try:
        render_pdf(pdf_path, context)
    except ApiError as exc:
        pdf_path = None  # other three formats remain usable; error surfaced in summary
        summary["pdf_error"] = exc.message
    report.html_path = workspace.relative(project_id, html_path)
    report.md_path = workspace.relative(project_id, md_path)
    report.json_path = workspace.relative(project_id, json_path)
    report.pdf_path = workspace.relative(project_id, pdf_path) if pdf_path else None
    session.commit()
    hub.emit("resource.changed", {"kind": "report", "id": report.id}, project_id)
    return report


def regenerate(session, project_id: str, report: Report) -> Report:
    root = workspace.ensure_workspace(project_id)
    context = build_context(session, project_id, report)
    folder = root / "reports" / report.id
    (folder / "report.html").write_text(render_html(context), encoding="utf-8")
    (folder / "report.md").write_text(render_markdown(context), encoding="utf-8")
    write_json(folder / "report.json", {"context": context, "report": as_dict(report)})
    if report.pdf_path:
        render_pdf(workspace.resolve(project_id, report.pdf_path), context)
    session.commit()
    return report


FORMAT_FIELD = {"html": "html_path", "pdf": "pdf_path", "json": "json_path", "md": "md_path"}
FORMAT_MIME = {
    "html": "text/html; charset=utf-8", "pdf": "application/pdf",
    "json": "application/json; charset=utf-8", "md": "text/markdown; charset=utf-8",
}


def export_path(report: Report, fmt: str) -> str | None:
    field = FORMAT_FIELD.get(fmt)
    if field is None:
        raise ApiError("UNSUPPORTED_FORMAT", f"不支持的报告格式: {fmt}", 422, {"supported": list(FORMAT_FIELD)})
    return getattr(report, field)
