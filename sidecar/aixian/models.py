"""PRD v0.1 core data model. Every table has id/created_at/updated_at;
asset tables additionally carry version + parent_version_id.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .util import now, uid


class BaseMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class VersionMixin:
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


def jdict() -> dict[str, Any]:
    return {}


def jlist() -> list[Any]:
    return []


class Project(Base, BaseMixin):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    workspace_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active")
    settings_json: Mapped[dict] = mapped_column(JSON, default=jdict)


class DataSource(Base, BaseMixin):
    __tablename__ = "datasources"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(32))  # sqlite/pg/mysql/plugin
    conn_json: Mapped[str] = mapped_column(Text, default="")  # encrypted at rest
    plugin_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="untested")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime)


class Dataset(Base, BaseMixin):
    __tablename__ = "datasets"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    schema_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    source_type: Mapped[str] = mapped_column(String(64), default="import")


class DatasetVersion(Base, BaseMixin, VersionMixin):
    __tablename__ = "dataset_versions"
    dataset_id: Mapped[str] = mapped_column(String(32), index=True)
    manifest_path: Mapped[str] = mapped_column(Text)
    data_path: Mapped[str] = mapped_column(Text)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    stats_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    created_by_job_id: Mapped[str | None] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    changelog: Mapped[str] = mapped_column(Text, default="")


class Record(Base, BaseMixin):
    __tablename__ = "records"
    __table_args__ = (
        Index("ix_records_version", "dataset_version_id"),
        Index("ix_records_hash", "hash"),
    )
    dataset_version_id: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(200))
    payload_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    label_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    split: Mapped[str] = mapped_column(String(16), default="train")
    hash: Mapped[str] = mapped_column(String(64), default="")


class CleaningPipeline(Base, BaseMixin, VersionMixin):
    __tablename__ = "cleaning_pipelines"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    nodes_json: Mapped[list] = mapped_column(JSON, default=jlist)


class PipelineRun(Base, BaseMixin):
    __tablename__ = "pipeline_runs"
    pipeline_id: Mapped[str] = mapped_column(String(32), index=True)
    source_version_id: Mapped[str] = mapped_column(String(32))
    output_version_id: Mapped[str | None] = mapped_column(String(32))
    job_id: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="running")
    stats_json: Mapped[dict] = mapped_column(JSON, default=jdict)


class Script(Base, BaseMixin, VersionMixin):
    __tablename__ = "scripts"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(16), default="py")  # py/sql
    path: Mapped[str] = mapped_column(Text)
    params_schema_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    description: Mapped[str] = mapped_column(Text, default="")


class AnnotationSchema(Base, BaseMixin):
    __tablename__ = "annotation_schemas"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    template_type: Mapped[str] = mapped_column(String(64), default="classification")
    schema_json: Mapped[dict] = mapped_column(JSON, default=jdict)


class AnnotationTask(Base, BaseMixin):
    __tablename__ = "annotation_tasks"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    dataset_version_id: Mapped[str] = mapped_column(String(32), index=True)
    schema_id: Mapped[str] = mapped_column(String(32))
    assignee: Mapped[str] = mapped_column(String(100), default="local")
    status: Mapped[str] = mapped_column(String(32), default="open")
    stats_json: Mapped[dict] = mapped_column(JSON, default=jdict)


class Annotation(Base, BaseMixin):
    __tablename__ = "annotations"
    __table_args__ = (Index("ix_annotations_task", "task_id", "record_id"),)
    task_id: Mapped[str] = mapped_column(String(32))
    record_id: Mapped[str] = mapped_column(String(32))
    label_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    annotator: Mapped[str] = mapped_column(String(100), default="local")
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), default="submitted")
    review_note: Mapped[str] = mapped_column(Text, default="")


class TrainingConfig(Base, BaseMixin, VersionMixin):
    __tablename__ = "training_configs"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    script_id: Mapped[str] = mapped_column(String(32))
    params_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    params_schema_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    env_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    finetune_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    runner_type: Mapped[str] = mapped_column(String(32), default="local")


class FineTuneTemplate(Base, BaseMixin, VersionMixin):
    __tablename__ = "finetune_templates"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(32), default="lora")  # lora/qlora/full/freeze
    description: Mapped[str] = mapped_column(Text, default="")
    dataset_format: Mapped[str] = mapped_column(String(32), default="alpaca")
    defaults_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    params_schema_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    builtin: Mapped[int] = mapped_column(Integer, default=0)


class AgentSession(Base, BaseMixin):
    __tablename__ = "agent_sessions"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    goal: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(String(32))
    plan_json: Mapped[list] = mapped_column(JSON, default=jlist)
    result_json: Mapped[list] = mapped_column(JSON, default=jlist)
    source: Mapped[str] = mapped_column(String(32), default="rules")
    status: Mapped[str] = mapped_column(String(32), default="planned")
    job_id: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str] = mapped_column(Text, default="")


class Run(Base, BaseMixin):
    __tablename__ = "runs"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    config_id: Mapped[str] = mapped_column(String(32))
    dataset_version_ids_json: Mapped[list] = mapped_column(JSON, default=jlist)
    code_version: Mapped[str] = mapped_column(String(64), default="")
    env_snapshot_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    runner_type: Mapped[str] = mapped_column(String(32), default="local")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    job_id: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    artifacts_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    error: Mapped[str] = mapped_column(Text, default="")


class Checkpoint(Base, BaseMixin):
    __tablename__ = "checkpoints"
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(Text)
    step: Mapped[int] = mapped_column(Integer, default=0)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    registered_model_name: Mapped[str | None] = mapped_column(String(200))


class Model(Base, BaseMixin, VersionMixin):
    """Registry of user-owned models. The platform stores a *reference*, never weights."""
    __tablename__ = "models"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(32), default="base")  # base/finetuned/adapter/endpoint/external
    adapter_type: Mapped[str] = mapped_column(String(32), default="")  # lora/qlora/full/none
    ref_json: Mapped[dict] = mapped_column(JSON, default=jdict)  # model_adapters config
    base_model_id: Mapped[str | None] = mapped_column(String(32))
    source_run_id: Mapped[str | None] = mapped_column(String(32))
    source_checkpoint_id: Mapped[str | None] = mapped_column(String(32))
    params_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    tags_json: Mapped[list] = mapped_column(JSON, default=jlist)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active/archived/missing
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime)


class EvalSuite(Base, BaseMixin, VersionMixin):
    __tablename__ = "eval_suites"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(32), default="accuracy")  # ab/boundary/accuracy
    description: Mapped[str] = mapped_column(Text, default="")
    cases_json: Mapped[list] = mapped_column(JSON, default=jlist)


class EvalRun(Base, BaseMixin):
    __tablename__ = "eval_runs"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    suite_id: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str | None] = mapped_column(String(32))
    model_ref_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    dataset_version_ids_json: Mapped[list] = mapped_column(JSON, default=jlist)
    scorer_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    metrics_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    results_json: Mapped[list] = mapped_column(JSON, default=jlist)
    report_id: Mapped[str | None] = mapped_column(String(32))
    job_id: Mapped[str | None] = mapped_column(String(32))


class ABTest(Base, BaseMixin):
    __tablename__ = "ab_tests"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    model_a_ref: Mapped[str] = mapped_column(Text, default="{}")
    model_b_ref: Mapped[str] = mapped_column(Text, default="{}")
    model_a_id: Mapped[str | None] = mapped_column(String(32))
    model_b_id: Mapped[str | None] = mapped_column(String(32))
    prompt_set_json: Mapped[list] = mapped_column(JSON, default=jlist)
    scorer_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    result_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    report_id: Mapped[str | None] = mapped_column(String(32))
    job_id: Mapped[str | None] = mapped_column(String(32))
    generated: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="draft")


class Report(Base, BaseMixin):
    __tablename__ = "reports"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(64), default="evaluation")
    linked_entities_json: Mapped[list] = mapped_column(JSON, default=jlist)
    summary_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    html_path: Mapped[str | None] = mapped_column(Text)
    pdf_path: Mapped[str | None] = mapped_column(Text)
    json_path: Mapped[str | None] = mapped_column(Text)
    md_path: Mapped[str | None] = mapped_column(Text)


class Job(Base, BaseMixin):
    __tablename__ = "jobs"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    runner_type: Mapped[str] = mapped_column(String(32), default="local")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    log_path: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)


class Plugin(Base, BaseMixin):
    __tablename__ = "plugins"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    plugin_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    manifest_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    enabled: Mapped[int] = mapped_column(Integer, default=0)
    permissions_json: Mapped[list] = mapped_column(JSON, default=jlist)
    source_path: Mapped[str] = mapped_column(Text, default="")
    permission_confirmed: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base, BaseMixin):
    __tablename__ = "audit_events"
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="local")
    action: Mapped[str] = mapped_column(String(200))
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str | None] = mapped_column(String(32))
    detail_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    at: Mapped[datetime] = mapped_column(DateTime, default=now)


# --- P2-b collaboration: global identity lives in the registry database -------

class User(Base, BaseMixin):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    color: Mapped[str] = mapped_column(String(16), default="#6c8cff")
    global_role: Mapped[str] = mapped_column(String(32), default="viewer")
    active: Mapped[int] = mapped_column(Integer, default=1)


class ProjectMember(Base, BaseMixin):
    __tablename__ = "project_members"
    __table_args__ = (Index("ix_member_project_user", "project_id", "user_id", unique=True),)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    invited_by: Mapped[str] = mapped_column(String(100), default="local")


# --- Scheduled jobs (project scoped, per-project SQLite) ----------------------

class Schedule(Base, BaseMixin):
    __tablename__ = "schedules"
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(64))  # script.run / pipeline.run / eval.run / command
    cron_expr: Mapped[str] = mapped_column(String(64), default="*/5 * * * *")
    target_id: Mapped[str] = mapped_column(String(32), default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=jdict)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_job_id: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str] = mapped_column(Text, default="")
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(100), default="local")
