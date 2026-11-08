"""Text annotation workbench: templates, tasks, labelling, review, Kappa, export."""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Body, Query
from sqlalchemy import func, select

from .. import workspace
from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..models import Annotation, AnnotationSchema, AnnotationTask, Record
from ..plugin_loader import registry
from ..services import datasets
from ..services.common import cohen_kappa
from ..util import as_dict, paginate, require, uid
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()

TEMPLATES = [
    {"template_type": "classification", "name": "文本分类", "schema_json": {
        "fields": [{"key": "label", "type": "select", "label": "类别", "options": ["正向", "负向", "中性"], "shortcuts": ["1", "2", "3"]}]}},
    {"template_type": "ner", "name": "命名实体识别", "schema_json": {
        "fields": [{"key": "entities", "type": "entities", "label": "实体", "options": ["人名", "地名", "机构", "时间"]}]}},
    {"template_type": "qa", "name": "问答对", "schema_json": {
        "fields": [{"key": "question", "type": "text", "label": "问题"}, {"key": "answer", "type": "textarea", "label": "答案"}]}},
    {"template_type": "summary", "name": "摘要", "schema_json": {
        "fields": [{"key": "summary", "type": "textarea", "label": "摘要"}]}},
    {"template_type": "quality_score", "name": "生成质量评分", "schema_json": {
        "fields": [{"key": "score", "type": "range", "label": "质量分", "min": 1, "max": 5},
                   {"key": "reason", "type": "text", "label": "理由"}]}},
    {"template_type": "preference", "name": "偏好排序", "schema_json": {
        "fields": [{"key": "order", "type": "ranking", "label": "排序", "options": ["A", "B"]}]}},
    {"template_type": "ab_human", "name": "A/B 人工标注", "schema_json": {
        "fields": [{"key": "winner", "type": "select", "label": "胜出", "options": ["A", "B", "平局"], "shortcuts": ["1", "2", "3"]}]}},
]


@contextmanager
def task_ctx(ident: str) -> Iterator[tuple[str, Any, AnnotationTask]]:
    pid = entity_project(AnnotationTask, ident)
    with project_session(pid) as session:
        yield pid, session, get_or_404(session, AnnotationTask, ident, "标注任务")


@router.get("/projects/{pid}/annotation-templates")
def annotation_templates(pid: str = ProjectId) -> Any:
    return {"items": TEMPLATES, "plugins": [
        {"template_type": f"plugin:{p.id}", "name": p.name, "schema_json": p.config_schema}
        for p, _, _ in registry.implementations("annotation_template")
    ]}


@router.get("/projects/{pid}/annotation-schemas")
def list_annotation_schemas(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(AnnotationSchema).where(AnnotationSchema.project_id == pid).order_by(AnnotationSchema.created_at.desc())
        return paginate(session, query, page, size)


@router.post("/projects/{pid}/annotation-schemas")
def create_annotation_schema(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "name")
    with project_session(pid) as session:
        row = AnnotationSchema(id=uid(), project_id=pid, name=data["name"],
                               template_type=data.get("template_type", "classification"),
                               schema_json=data.get("schema_json") or {})
        session.add(row)
        session.commit()
        return as_dict(row)


@router.get("/projects/{pid}/annotation-tasks")
def list_annotation_tasks(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(AnnotationTask).where(AnnotationTask.project_id == pid).order_by(AnnotationTask.created_at.desc())
        return paginate(session, query, page, size)


@router.post("/projects/{pid}/annotation-tasks")
def create_annotation_task(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "dataset_version_id", "schema_id")
    with project_session(pid) as session:
        datasets.get_version(session, data["dataset_version_id"])
        get_or_404(session, AnnotationSchema, data["schema_id"], "标注模板")
        row = AnnotationTask(
            id=uid(), project_id=pid, name=data.get("name") or "标注任务",
            dataset_version_id=data["dataset_version_id"], schema_id=data["schema_id"],
            assignee=data.get("assignee", "local"), status="open", stats_json={},
        )
        session.add(row)
        session.commit()
        return as_dict(row)


def _task_stats(session, task: AnnotationTask) -> dict[str, Any]:
    total = session.scalar(select(func.count()).select_from(Record).where(
        Record.dataset_version_id == task.dataset_version_id)) or 0
    annotations = session.execute(select(Annotation).where(Annotation.task_id == task.id)).scalars().all()
    by_record: dict[str, list[Annotation]] = {}
    for item in annotations:
        by_record.setdefault(item.record_id, []).append(item)
    pairs: list[tuple[Any, Any]] = []
    for items in by_record.values():
        distinct = {}
        for item in items:
            distinct.setdefault(item.annotator, item.label_json.get("label"))
        values = list(distinct.values())
        if len(values) >= 2:
            pairs.append((values[0], values[1]))
        elif items and "auto_label" in items[0].label_json:
            pairs.append((items[0].label_json.get("auto_label"), items[0].label_json.get("label")))
    stats = {
        "record_count": total,
        "annotated": len(by_record),
        "submitted": sum(1 for a in annotations if a.status == "submitted"),
        "approved": sum(1 for a in annotations if a.status == "approved"),
        "rejected": sum(1 for a in annotations if a.status == "rejected"),
        "coverage": round(len(by_record) / total, 4) if total else 0.0,
        "cohen_kappa": cohen_kappa(pairs) if pairs else None,
    }
    return stats


@router.get("/annotation-tasks/{id}")
def get_annotation_task(id: str) -> Any:
    with task_ctx(id) as (pid, session, row):
        stats = _task_stats(session, row)
        row.stats_json = stats
        schema = session.get(AnnotationSchema, row.schema_id)
        session.commit()
        return {**as_dict(row), "schema": as_dict(schema) if schema else {}}


@router.get("/annotation-tasks/{id}/records")
def task_records(id: str, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=500),
                 status: str | None = None) -> Any:
    with task_ctx(id) as (_, session, row):
        result = datasets.query_records(session, row.dataset_version_id, page, size)
        annotations = {a.record_id: as_dict(a) for a in session.execute(
            select(Annotation).where(Annotation.task_id == id)).scalars().all()}
        for item in result["items"]:
            item["annotation"] = annotations.get(item["id"])
        if status:
            result["items"] = [i for i in result["items"]
                               if (status == "unlabeled" and not i["annotation"])
                               or (status != "unlabeled" and i["annotation"] and i["annotation"]["status"] == status)]
        return result


@router.post("/annotation-tasks/{id}/annotations")
def save_annotation(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "record_id", "label_json")
    with task_ctx(id) as (pid, session, row):
        existing = session.execute(select(Annotation).where(
            Annotation.task_id == id, Annotation.record_id == data["record_id"],
            Annotation.annotator == data.get("annotator", "local"))).scalars().first()
        if existing:
            existing.label_json = data["label_json"]
            existing.status = data.get("status", "submitted")
            item = existing
        else:
            item = Annotation(task_id=id, record_id=data["record_id"], label_json=data["label_json"],
                              annotator=data.get("annotator", "local"), status=data.get("status", "submitted"))
            session.add(item)
        session.commit()
        row.stats_json = _task_stats(session, row)
        session.commit()
        record(session, "annotation.save", "annotation", item.id,
               {"task_id": id, "record_id": data["record_id"]}, pid)
        return as_dict(item)


@router.post("/annotation-tasks/{id}/review")
def review_annotations(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    decision = payload.get("decision", "approve")
    if decision not in ("approve", "reject"):
        raise ApiError("VALIDATION_ERROR", "decision 仅支持 approve / reject", 422)
    record_ids = payload.get("record_ids") or ([payload["record_id"]] if payload.get("record_id") else [])
    if not record_ids:
        raise ApiError("VALIDATION_ERROR", "需要 record_id 或 record_ids", 422)
    with task_ctx(id) as (pid, session, row):
        rows = session.execute(select(Annotation).where(
            Annotation.task_id == id, Annotation.record_id.in_(record_ids))).scalars().all()
        for item in rows:
            item.status = "approved" if decision == "approve" else "rejected"
            item.reviewed_by = payload.get("reviewer", "local")
            item.review_note = payload.get("note", "")
        row.stats_json = _task_stats(session, row)
        if row.stats_json["coverage"] >= 1 and row.stats_json["rejected"] == 0:
            row.status = "completed"
        session.commit()
        record(session, "annotation.review", "annotation_task", id,
               {"decision": decision, "count": len(rows)}, pid)
        return {"reviewed": len(rows), "stats": row.stats_json}


@router.post("/annotation-tasks/{id}/export")
def export_annotations(id: str, payload: dict[str, Any] = Body(default={})) -> Any:
    with task_ctx(id) as (pid, session, row):
        annotations = {a.record_id: a for a in session.execute(
            select(Annotation).where(Annotation.task_id == id)).scalars().all()}
        records = session.execute(select(Record).where(
            Record.dataset_version_id == row.dataset_version_id)).scalars().all()
        only_approved = bool(payload.get("only_approved", False))
        target = workspace.new_asset_path(pid, "annotations", f"{id}.jsonl")
        count = 0
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            for rec in records:
                annotation = annotations.get(rec.id)
                if annotation is None or (only_approved and annotation.status != "approved"):
                    continue
                handle.write(json.dumps({
                    "record_id": rec.id, "payload": rec.payload_json, "label": annotation.label_json,
                    "annotator": annotation.annotator, "status": annotation.status,
                    "dataset_version_id": row.dataset_version_id,
                }, ensure_ascii=False, default=str) + "\n")
                count += 1
        record(session, "annotation.export", "annotation_task", id, {"count": count}, pid)
        return {"path": workspace.relative(pid, target), "uri": workspace.uri(pid, "annotation_export", id),
                "record_count": count, "stats": _task_stats(session, row)}
