"""Training runners: local process / SSH / Docker / plugin backend, with lineage."""
from __future__ import annotations

import asyncio
import json
import platform
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .. import security, workspace
from ..database import project_session
from ..errors import ApiError
from ..models import Checkpoint, DatasetVersion, Run, Script, TrainingConfig
from ..plugin_loader import registry
from ..plugin_sdk import JobContext as PluginJobContext
from ..util import as_dict, now, sha256_file, uid, write_json

RUNNER_TYPES = ("local", "ssh", "docker")


def build_spec(project_id: str, run: Run, config: TrainingConfig, script: Script, ctx) -> dict[str, Any]:
    root = workspace.ensure_workspace(project_id)
    run_dir = root / "runs" / run.id
    (run_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
    (run_dir / "adapters").mkdir(parents=True, exist_ok=True)
    ext = "sql" if script.type == "sql" else "py"
    content = (workspace.resolve(project_id, Path("scripts") / f"{script.id}.{ext}")).read_text(encoding="utf-8")
    code_path = run_dir / f"train.{ext}"
    code_path.write_text(content, encoding="utf-8")
    params_path = write_json(run_dir / "params.json", config.params_json)
    env = {
        "AIXIAN_PROJECT_ID": project_id,
        "AIXIAN_RUN_ID": run.id,
        "AIXIAN_JOB_ID": ctx.job_id,
        "AIXIAN_PARAMS": str(params_path),
        "AIXIAN_RUN_DIR": str(run_dir),
        "AIXIAN_CHECKPOINT_DIR": str(run_dir / "checkpoints"),
        "AIXIAN_METRICS_PATH": str(run_dir / "metrics.json"),
        "AIXIAN_OUTPUT": str(run_dir / "output.jsonl"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    finetune = config.finetune_json or {}
    if finetune:
        from . import finetune as finetune_service
        with project_session(project_id) as _db:
            base = finetune_service.resolve_base_model(_db, project_id, config)
        params_path_ft = write_json(run_dir / "finetune_params.json", finetune)
        env.update({
            "AIXIAN_BASE_MODEL": base["path"],
            "AIXIAN_BASE_MODEL_NAME": base["name"],
            "AIXIAN_FINETUNE_METHOD": base["method"],
            "AIXIAN_FINETUNE_PARAMS": str(params_path_ft),
            "AIXIAN_DATASET_FORMAT": base["format"],
            "AIXIAN_ADAPTER_OUTPUT": str(run_dir / base["adapter_output"]),
        })
    return {
        "run_dir": run_dir,
        "code_path": code_path,
        "params_path": params_path,
        "command": [sys.executable, str(code_path), "--params", str(params_path)],
        "env": env,
        "code_version": sha256_file(code_path),
        "env_json": config.env_json or {},
    }


class LocalRunner:
    async def execute(self, ctx, spec: dict[str, Any]) -> int:
        return await ctx.exec(spec["command"], spec["run_dir"], spec["env"])


class SSHRunner:
    async def execute(self, ctx, spec: dict[str, Any]) -> int:
        conf = spec["env_json"].get("ssh") or {}
        if not conf.get("host"):
            raise ApiError("SSH_CONFIG", "SSH runner 需要 env_json.ssh.host/user", 422)
        return await asyncio.to_thread(self._blocking, ctx, spec, conf)

    def _blocking(self, ctx, spec, conf) -> int:
        try:
            import paramiko
        except ImportError as exc:
            raise ApiError("MISSING_DEPENDENCY", "SSH runner 需要安装 paramiko", 500, str(exc)) from exc
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=conf["host"], port=int(conf.get("port", 22)), username=conf.get("user"),
            password=conf.get("password"), key_filename=conf.get("key_path"), timeout=20,
        )
        try:
            remote_dir = conf.get("remote_dir", "/tmp/aixian-runs")
            sftp = client.open_sftp()
            _mkdir_p(sftp, remote_dir)
            for local in (spec["code_path"], spec["params_path"]):
                sftp.put(str(local), f"{remote_dir}/{Path(local).name}")
            sftp.close()
            command = " ".join(_quote(part) for part in [sys.executable, f"{remote_dir}/{spec['code_path'].name}", "--params", f"{remote_dir}/{spec['params_path'].name}"])
            prefix = f"cd {_quote(remote_dir)} && "
            env_prefix = " ".join(f"{k}={_quote(v)}" for k, v in spec["env"].items() if k.startswith("AIXIAN_"))
            stdin, stdout, _ = client.exec_command(prefix + env_prefix + " " + command, get_pty=True)
            for line in iter(stdout.readline, ""):
                ctx.log(line.rstrip("\r\n"))
            return int(stdout.channel.recv_exit_status())
        finally:
            client.close()


class DockerRunner:
    async def execute(self, ctx, spec: dict[str, Any]) -> int:
        conf = spec["env_json"].get("docker") or {}
        image = conf.get("image")
        if not image:
            raise ApiError("DOCKER_CONFIG", "Docker runner 需要 env_json.docker.image", 422)
        return await asyncio.to_thread(self._blocking, ctx, spec, image)

    def _blocking(self, ctx, spec, image) -> int:
        try:
            import docker
        except ImportError as exc:
            raise ApiError("MISSING_DEPENDENCY", "Docker runner 需要安装 docker SDK", 500, str(exc)) from exc
        client = docker.from_env()
        container = client.containers.run(
            image,
            ["python", f"/workspace/runs/{spec['run_dir'].name}/train.py",
             "--params", f"/workspace/runs/{spec['run_dir'].name}/params.json"],
            volumes={str(spec["run_dir"].parent.parent): {"bind": "/workspace", "mode": "rw"}},
            working_dir="/workspace",
            environment={"AIXIAN_RUN_DIR": f"/workspace/runs/{spec['run_dir'].name}",
                         "AIXIAN_CHECKPOINT_DIR": "/workspace/checkpoints",
                         "AIXIAN_METRICS_PATH": "/workspace/metrics.json"},
            detach=True,
        )
        try:
            for chunk in container.logs(stream=True, follow=True):
                ctx.log(chunk.decode("utf-8", errors="replace").rstrip("\r\n"))
            status = container.wait()
            return int(status.get("StatusCode", 1))
        finally:
            try:
                container.remove(force=True)
            except Exception:
                pass


class PluginRunner:
    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id

    async def execute(self, ctx, spec: dict[str, Any]) -> int:
        plugin = next((p for p in registry.discover() if p.id == self.plugin_id), None)
        if plugin is None:
            raise ApiError("PLUGIN_NOT_FOUND", f"训练后端插件未安装: {self.plugin_id}", 404)
        registry.require_permission(plugin, "training:submit")
        impl = next((i for _, _, i in registry.implementations("training_backend", {plugin.id})), None)
        if impl is None:
            raise ApiError("PLUGIN_IMPL", "插件未实现 training_backend", 500)
        job = PluginJobContext(
            job_id=ctx.job_id, project_id=ctx.project_id, workdir=str(spec["run_dir"]),
            command=" ".join(spec["command"]), params=json.loads(spec["params_path"].read_text(encoding="utf-8")),
            env=spec["env"], log_path=str(ctx.log_path), log=ctx.log,
        )
        remote_id = await asyncio.to_thread(impl.submit, job)
        ctx.log(f"[aixian] 插件后端已提交远端任务 {remote_id}")
        while True:
            status = await asyncio.to_thread(impl.status, remote_id)
            state = status.state if hasattr(status, "state") else str(status)
            if state in ("succeeded", "failed", "cancelled"):
                for line in impl.logs(remote_id):
                    ctx.log(line)
                return 0 if state == "succeeded" else 1
            await asyncio.sleep(1.0)


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\\''") + "'"


def _mkdir_p(sftp, remote_dir: str) -> None:
    parts = remote_dir.strip("/").split("/")
    current = ""
    for part in parts:
        current += "/" + part
        try:
            sftp.stat(current)
        except IOError:
            sftp.mkdir(current)


def get_runner(runner_type: str):
    if runner_type == "local":
        return LocalRunner()
    if runner_type == "ssh":
        return SSHRunner()
    if runner_type == "docker":
        return DockerRunner()
    if runner_type.startswith("plugin:"):
        return PluginRunner(runner_type.split(":", 1)[1])
    raise ApiError("UNSUPPORTED_RUNNER", f"未知 runner: {runner_type}", 422, {"supported": RUNNER_TYPES})


def env_snapshot(config: TrainingConfig) -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executable": sys.executable,
        "runner_type": config.runner_type,
        "env": security.mask_config(config.env_json or {}),
        "captured_at": now().isoformat(),
    }


async def run_worker(project_id: str, run_id: str, ctx) -> dict[str, Any]:
    with project_session(project_id) as session:
        run = session.get(Run, run_id)
        if run is None:
            raise ApiError("NOT_FOUND", "训练任务不存在", 404, run_id)
        config = session.get(TrainingConfig, run.config_id)
        script = session.get(Script, config.script_id) if config else None
        if config is None or script is None:
            raise ApiError("NOT_FOUND", "训练配置或脚本不存在", 404)
        runner_type = run.runner_type
        run.status = "running"
        run.started_at = now()
        session.commit()
    spec = build_spec(project_id, run, config, script, ctx)
    with project_session(project_id) as session:
        run = session.get(Run, run_id)
        run.code_version = spec["code_version"]
        run.env_snapshot_json = env_snapshot(config)
        session.commit()
    ctx.log(f"[aixian] Run {run_id} 启动 ({runner_type}) code_version={spec['code_version'][:12]}")
    runner = get_runner(runner_type)
    exit_code = await runner.execute(ctx, spec)
    metrics = _collect_metrics(spec["run_dir"])
    artifacts = _collect_artifacts(project_id, spec["run_dir"])
    with project_session(project_id) as session:
        run = session.get(Run, run_id)
        run.metrics_json = metrics
        run.artifacts_json = artifacts
        run.finished_at = now()
        run.status = "succeeded" if exit_code == 0 else "failed"
        if exit_code != 0:
            run.error = f"训练进程退出码 {exit_code}"
        _discover_checkpoints(session, run_id, spec["run_dir"], metrics)
        adapters: list[dict[str, Any]] = []
        if exit_code == 0 and config.finetune_json:
            from . import finetune as finetune_service
            adapters = finetune_service.register_adapters(
                session, project_id, run, config, spec["run_dir"])
        # Rebind a NEW dict: SQLAlchemy does not track in-place JSON mutations.
        artifacts = {**artifacts, "registered_adapters": adapters}
        run.artifacts_json = artifacts
        session.commit()
    if exit_code != 0:
        raise ApiError("TRAINING_FAILED", f"训练进程退出码 {exit_code}", 500, artifacts)
    return {"run_id": run_id, "status": "succeeded", "metrics": metrics,
            "artifacts": artifacts, "registered_adapters": artifacts.get("registered_adapters", [])}


def _collect_metrics(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "metrics.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"value": data}
    except (OSError, ValueError):
        return {}


def _collect_artifacts(project_id: str, run_dir: Path) -> dict[str, Any]:
    files = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file():
            files.append({"path": workspace.relative(project_id, path), "size": path.stat().st_size})
    return {"files": files, "run_dir": workspace.relative(project_id, run_dir)}


def _discover_checkpoints(session, run_id: str, run_dir: Path, metrics: dict[str, Any]) -> None:
    folder = run_dir / "checkpoints"
    if not folder.exists():
        return
    existing = {row.path for row in session.execute(select(Checkpoint).where(Checkpoint.run_id == run_id)).scalars().all()}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or str(path) in existing:
            continue
        step = 0
        import re
        match = re.search(r"(\d+)", path.stem)
        if match:
            step = int(match.group(1))
        session.add(Checkpoint(run_id=run_id, path=str(path), step=step, metrics_json=metrics))


def register_model(session, project_id: str, run_id: str, checkpoint_id: str | None, name: str) -> Checkpoint:
    run = session.get(Run, run_id)
    if run is None:
        raise ApiError("NOT_FOUND", "训练任务不存在", 404, run_id)
    checkpoint = None
    if checkpoint_id:
        checkpoint = session.get(Checkpoint, checkpoint_id)
        if checkpoint is None or checkpoint.run_id != run_id:
            raise ApiError("NOT_FOUND", "checkpoint 不存在", 404, checkpoint_id)
    if checkpoint is None:
        checkpoint = session.execute(
            select(Checkpoint).where(Checkpoint.run_id == run_id).order_by(Checkpoint.step.desc())
        ).scalars().first()
    if checkpoint is None:
        checkpoint = Checkpoint(run_id=run_id, path=str(workspace.resolve(project_id, Path("runs") / run_id)),
                               step=0, metrics_json=run.metrics_json)
        session.add(checkpoint)
        session.flush()
    checkpoint.registered_model_name = name
    session.commit()
    return checkpoint


def metrics_dashboard(session, project_id: str) -> dict[str, Any]:
    runs = session.execute(select(Run).where(Run.project_id == project_id)).scalars().all()
    series = []
    for run in runs:
        series.append({
            "run_id": run.id, "name": run.name, "status": run.status,
            "runner_type": run.runner_type, "metrics": run.metrics_json or {},
            "started_at": run.started_at.isoformat() if run.started_at else None,
        })
    checkpoints = session.execute(select(Checkpoint)).scalars().all()
    return {
        "runs": series,
        "run_count": len(runs),
        "succeeded": sum(1 for r in runs if r.status == "succeeded"),
        "checkpoint_count": len(checkpoints),
        "registered_models": [as_dict(c) for c in checkpoints if c.registered_model_name],
    }
