from __future__ import annotations

import json
import queue
import threading
import uuid
import webbrowser
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, jsonify, render_template, request, send_file

from agents import Orchestrator
from config import get_settings
from utils import close_run_logger, create_run_logger


_BASE_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _BASE_DIR / "web" / "templates"
_STATIC_DIR = _BASE_DIR / "web" / "static"

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sse_payload(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\\n\\n"


def _create_job(repo_url: str, analysis_type: str) -> str:
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "repo_url": repo_url,
            "analysis_type": analysis_type,
            "status": "queued",
            "created_at": _now_text(),
            "updated_at": _now_text(),
            "queue": queue.Queue(),
            "log_history": [],
            "result": None,
            "error": None,
            "log_path": "",
        }
    return job_id


def _get_job(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


def _set_job_status(job_id: str, status: str, **extra: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["status"] = status
        job["updated_at"] = _now_text()
        for key, value in extra.items():
            job[key] = value


def _push_event(job_id: str, payload: dict[str, Any]) -> None:
    payload.setdefault("timestamp", _now_text())
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["updated_at"] = _now_text()
        if payload.get("type") == "log":
            message = str(payload.get("message", "")).strip()
            if message:
                job["log_history"].append(message)
        event_queue: queue.Queue = job["queue"]
    event_queue.put(payload)


def _build_result(job_id: str) -> dict[str, Any]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return {}
        payload = {
            "jobId": job_id,
            "status": job.get("status", "unknown"),
            "repoUrl": job.get("repo_url", ""),
            "analysisType": job.get("analysis_type", ""),
            "createdAt": job.get("created_at", ""),
            "updatedAt": job.get("updated_at", ""),
            "logPath": job.get("log_path", ""),
            "logHistory": list(job.get("log_history", [])),
            "error": job.get("error", None),
        }
        result = job.get("result")
        if isinstance(result, dict):
            payload.update(result)
        return payload


def _to_user_error_message(exc: Exception) -> str:
    text = str(exc).strip()
    lowered = text.lower()
    if "rate limit" in lowered and "github" in lowered:
        return (
            "GitHub API 触发限流。请在页面顶部填写 GitHub Token（可选）后重试，"
            "或稍后再试。"
        )
    return text or "任务失败"


def _run_analysis_job(
    job_id: str,
    repo_url: str,
    analysis_type: str,
    api_key: str,
    github_token: str,
) -> None:
    base_settings = get_settings()
    runtime_settings = replace(
        base_settings,
        deepseek_api_key=api_key.strip(),
        github_token=github_token.strip() or base_settings.github_token,
    )

    logger_name = f"github_project_analyzer.web.{job_id}"
    run_logger, run_log_path = create_run_logger(runtime_settings.logs_dir, logger_name=logger_name)
    _set_job_status(job_id, "running", log_path=str(run_log_path))
    _push_event(job_id, {"type": "log", "message": "[Pipeline] Web 任务已启动"})

    def progress_callback(message: str) -> None:
        _push_event(job_id, {"type": "log", "message": f"[Pipeline] {message}"})

    try:
        orchestrator = Orchestrator(
            settings=runtime_settings,
            progress_callback=progress_callback,
            logger=run_logger,
        )
        result = orchestrator.run(repo_url=repo_url, analysis_type=analysis_type)

        report_paths = result.get("report_paths", {})
        html_content = ""
        html_path_str = str(report_paths.get("html", ""))
        if html_path_str:
            html_path = Path(html_path_str)
            if html_path.exists():
                html_content = html_path.read_text(encoding="utf-8")

        result_payload = {
            "analysisLabel": result.get("analysis_label", ""),
            "finalStatePath": result.get("final_state_path", ""),
            "reportPaths": report_paths,
            "criticHistory": result.get("critic_history", []),
            "selectedCriticRound": result.get("selected_critic_round", 0),
            "selectedCriticScore": result.get("selected_critic_score", 0),
            "selectedCriticIncomplete": result.get("selected_critic_incomplete", False),
            "selectedCriticPromptLeakage": result.get("selected_critic_prompt_leakage", False),
            "htmlContent": html_content,
            "downloadUrls": {
                fmt: f"/api/download/{job_id}/{fmt}"
                for fmt in ("docx", "html", "md")
                if fmt in report_paths
            },
        }

        _set_job_status(job_id, "done", result=result_payload, error=None)
        _push_event(job_id, {"type": "done", "message": "分析任务完成。"})
    except Exception as exc:  # noqa: BLE001
        run_logger.exception("state=FAILED | agent=webapp | job_id=%s", job_id)
        user_error = _to_user_error_message(exc)
        _set_job_status(job_id, "error", error=user_error)
        _push_event(job_id, {"type": "error", "message": f"任务失败: {user_error}"})
    finally:
        close_run_logger(run_logger)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(_TEMPLATE_DIR),
        static_folder=str(_STATIC_DIR),
        static_url_path="/static",
    )

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.post("/api/start-analysis")
    def start_analysis() -> Response:
        payload = request.get_json(silent=True) or {}
        repo_url = str(payload.get("repoUrl", "")).strip()
        analysis_type = str(payload.get("analysisType", "")).strip()
        api_key = str(payload.get("apiKey", "")).strip()
        github_token = str(payload.get("githubToken", "")).strip()

        if not repo_url:
            return jsonify({"error": "repoUrl 不能为空"}), 400
        if not api_key:
            return jsonify({"error": "apiKey 不能为空"}), 400
        if analysis_type not in {"econ", "ethics"}:
            return jsonify({"error": "analysisType 必须为 econ 或 ethics"}), 400

        job_id = _create_job(repo_url=repo_url, analysis_type=analysis_type)
        worker = threading.Thread(
            target=_run_analysis_job,
            args=(job_id, repo_url, analysis_type, api_key, github_token),
            daemon=True,
        )
        worker.start()

        return jsonify(
            {
                "jobId": job_id,
                "streamUrl": f"/api/stream/{job_id}",
                "resultUrl": f"/api/result/{job_id}",
                "downloadBaseUrl": f"/api/download/{job_id}",
            }
        )

    @app.get("/api/stream/<job_id>")
    def stream(job_id: str) -> Response:
        job = _get_job(job_id)
        if not job:
            abort(404, description="job not found")

        def event_stream() -> Any:
            with _JOBS_LOCK:
                snapshot = _JOBS.get(job_id)
                if not snapshot:
                    yield _sse_payload({"type": "error", "message": "任务不存在"})
                    return
                history = list(snapshot.get("log_history", []))
                status = snapshot.get("status", "queued")
                error = snapshot.get("error", "")
                event_queue: queue.Queue = snapshot["queue"]

            for line in history:
                yield _sse_payload({"type": "log", "message": line, "history": True})

            if status == "done":
                yield _sse_payload({"type": "done", "message": "分析任务完成。"})
                return
            if status == "error":
                yield _sse_payload({"type": "error", "message": error or "任务失败"})
                return

            while True:
                try:
                    event = event_queue.get(timeout=1.0)
                    yield _sse_payload(event)
                    if event.get("type") in {"done", "error"}:
                        break
                except queue.Empty:
                    latest = _get_job(job_id)
                    if not latest:
                        yield _sse_payload({"type": "error", "message": "任务不存在"})
                        break
                    latest_status = latest.get("status")
                    if latest_status == "done":
                        yield _sse_payload({"type": "done", "message": "分析任务完成。"})
                        break
                    if latest_status == "error":
                        yield _sse_payload(
                            {"type": "error", "message": latest.get("error") or "任务失败"}
                        )
                        break
                    yield ": ping\\n\\n"

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return Response(event_stream(), headers=headers, mimetype="text/event-stream")

    @app.get("/api/result/<job_id>")
    def result(job_id: str) -> Response:
        payload = _build_result(job_id)
        if not payload:
            abort(404, description="job not found")
        return jsonify(payload)

    @app.get("/api/download/<job_id>/<fmt>")
    def download(job_id: str, fmt: str) -> Response:
        if fmt not in {"docx", "html", "md"}:
            abort(404, description="unsupported format")

        payload = _build_result(job_id)
        if not payload:
            abort(404, description="job not found")
        if payload.get("status") != "done":
            return jsonify({"error": "任务尚未完成，无法下载"}), 409

        report_paths = payload.get("reportPaths", {})
        path_str = str(report_paths.get(fmt, ""))
        if not path_str:
            abort(404, description="file not found")

        report_path = Path(path_str)
        if not report_path.exists():
            abort(404, description="file not found")

        mime_types = {
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "html": "text/html",
            "md": "text/markdown",
        }
        return send_file(
            str(report_path),
            as_attachment=True,
            download_name=report_path.name,
            mimetype=mime_types[fmt],
        )

    return app


def run_web_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> int:
    app = create_app()
    show_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{show_host}:{port}"

    print(f"[Web] 启动前端服务: {url}")
    if open_browser:
        timer = threading.Timer(1.0, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()

    app.run(host=host, port=port, debug=False, use_reloader=False)
    return 0
