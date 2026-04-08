from __future__ import annotations

"""Project entrypoint.

Default behavior starts the Web UI.
CLI mode is enabled via --cli or by passing task arguments.
"""

import argparse
import traceback
from pathlib import Path
from typing import Any, Final

from agents import Orchestrator
from config import get_settings
from utils import close_run_logger, create_run_logger
from webapp import run_web_server


EXIT_OK: Final[int] = 0
EXIT_FAILED: Final[int] = 1
EXIT_INTERRUPTED: Final[int] = 130

ANALYSIS_CHOICES: Final[list[str]] = ["econ", "ethics", "工程经济", "伦理法规", "1", "2"]


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _prompt_repo_url() -> str:
    while True:
        value = input("请输入 GitHub 仓库链接 (https://github.com/<owner>/<repo>): ").strip()
        if value:
            return value
        print("仓库链接不能为空，请重新输入。")


def _prompt_analysis_type() -> str:
    print("请选择分析方向：")
    print("1) 工程经济与项目管理")
    print("2) 伦理法规与工程安全")
    print("也可输入: econ / ethics")

    while True:
        value = input("请输入 1 或 2: ").strip()
        if value in {"1", "2", "econ", "ethics", "工程经济", "伦理法规"}:
            return value
        print("输入无效，请输入 1/2 或 econ/ethics。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GitHub 热门项目多智能体分析器（工程经济 / 伦理法规 二选一）"
    )

    mode_group = parser.add_argument_group("运行模式")
    mode_group.add_argument(
        "--cli",
        action="store_true",
        help="使用命令行模式运行（默认启动 Web 页面）",
    )

    web_group = parser.add_argument_group("Web 模式参数")
    web_group.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Web 服务监听地址（默认 127.0.0.1）",
    )
    web_group.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Web 服务端口（默认 8765）",
    )
    web_group.add_argument(
        "--no-open-browser",
        action="store_true",
        help="启动 Web 服务时不自动打开浏览器",
    )

    cli_group = parser.add_argument_group("CLI 任务参数")
    cli_group.add_argument(
        "--repo-url",
        type=str,
        help="目标仓库地址，例如 https://github.com/owner/repo",
    )
    cli_group.add_argument(
        "--analysis",
        type=str,
        choices=ANALYSIS_CHOICES,
        help="分析方向：econ/工程经济/1 或 ethics/伦理法规/2",
    )
    cli_group.add_argument(
        "--quiet",
        action="store_true",
        help="关闭流水线进度日志输出",
    )
    cli_group.add_argument(
        "--debug",
        action="store_true",
        help="发生异常时打印完整堆栈",
    )

    return parser


def _print_result_summary(result: dict[str, Any], log_path: Path) -> None:
    print("\n=== 报告生成完成 ===")
    print(f"分析方向: {_safe_text(result.get('analysis_label'), 'N/A')}")
    print(f"状态缓存: {_safe_text(result.get('final_state_path'), 'N/A')}")
    print(f"日志文件: {log_path}")
    print("输出文件:")

    report_paths = result.get("report_paths", {})
    if isinstance(report_paths, dict):
        for kind, path in report_paths.items():
            print(f"- {_safe_text(kind).upper()}: {_safe_text(path)}")

    history = result.get("critic_history", [])
    if not isinstance(history, list) or not history:
        return

    last = history[-1] if isinstance(history[-1], dict) else {}
    selected_round = _safe_int(result.get("selected_critic_round"), _safe_int(last.get("round"), 0))
    selected_score = _safe_float(result.get("selected_critic_score"), _safe_float(last.get("score"), 0.0))
    selected_entry = next(
        (
            item
            for item in history
            if isinstance(item, dict) and _safe_int(item.get("round"), -1) == selected_round
        ),
        last,
    )

    print(
        "Critic 最终评分: "
        f"{selected_score:.2f} | "
        f"采用轮次: {selected_round} | "
        f"有效字数: {_safe_int(selected_entry.get('effective_length'), 0)} | "
        f"通过: {bool(selected_entry.get('pass', False))}"
    )


def run_cli(args: argparse.Namespace) -> int:
    repo_url = args.repo_url or _prompt_repo_url()
    analysis_type = args.analysis or _prompt_analysis_type()

    settings = get_settings()
    run_logger, log_path = create_run_logger(settings.logs_dir)

    def progress_log(message: str) -> None:
        if not args.quiet:
            print(f"[Pipeline] {message}")

    orchestrator = Orchestrator(
        settings=settings,
        progress_callback=progress_log,
        logger=run_logger,
    )

    try:
        run_logger.info(
            "state=START | agent=main | mode=cli | repo_url=%s | analysis_type=%s",
            repo_url,
            analysis_type,
        )
        result = orchestrator.run(repo_url=repo_url, analysis_type=analysis_type)
        run_logger.info("state=DONE | agent=main | mode=cli | 任务执行完成")
        _print_result_summary(result=result, log_path=log_path)
        return EXIT_OK
    except KeyboardInterrupt:
        run_logger.warning("state=INTERRUPTED | agent=main | mode=cli | 用户中断任务")
        print("\n[Warn] 任务被用户中断。")
        print(f"日志文件: {log_path}")
        return EXIT_INTERRUPTED
    except Exception as exc:  # noqa: BLE001
        run_logger.exception("state=FAILED | agent=main | mode=cli | 任务执行失败")
        print(f"\n[Error] 任务执行失败: {exc}")
        if args.debug:
            traceback.print_exc()
        print(f"日志文件: {log_path}")
        return EXIT_FAILED
    finally:
        close_run_logger(run_logger)


def run_web(args: argparse.Namespace) -> int:
    try:
        return run_web_server(
            host=args.host,
            port=args.port,
            open_browser=(not args.no_open_browser),
        )
    except KeyboardInterrupt:
        print("\n[Web] 服务已停止。")
        return EXIT_INTERRUPTED
    except Exception as exc:  # noqa: BLE001
        print(f"\n[Error] Web 服务启动失败: {exc}")
        if args.debug:
            traceback.print_exc()
        return EXIT_FAILED


def should_use_cli_mode(args: argparse.Namespace) -> bool:
    return bool(args.cli or args.repo_url or args.analysis)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if should_use_cli_mode(args):
        return run_cli(args)
    return run_web(args)


if __name__ == "__main__":
    raise SystemExit(main())
