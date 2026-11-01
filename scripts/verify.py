# 本地和 CI 共用的质量检查入口；只协调固定命令，不安装依赖或修改应用配置。
# 各检查按依赖顺序执行并产生 passed/failed/blocked；失败与缺失前提都非零退出。
# 子进程原始输出不进入共享报告，防止测试异常携带连接串、凭证或模型原文。
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

Status = Literal["passed", "failed", "blocked"]
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    # 命令与依赖由仓库代码定义；不接受外部任意命令文本，不使用 shell 拼接。
    name: str
    command: tuple[str, ...]
    cwd: Path
    requires: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict[str, str])
    preflight: bool = False
    summary_path: Path | None = None


@dataclass(frozen=True)
class Result:
    # 固定原因码取代外部异常原文；returncode 保留实际工具失败信息。
    name: str
    status: Status
    reason: str
    returncode: int | None = None
    diagnostics: dict[str, object] | None = None


def supported_node_version(version: str) -> bool:
    # 对应 frontend/package.json 的 ^20.19.0 || >=22.12.0，升级版本约束时同步修改。
    try:
        parts = tuple(int(part) for part in version.removeprefix("v").strip().split("."))
    except ValueError:
        return False
    return len(parts) == 3 and ((parts[0] == 20 and parts >= (20, 19, 0)) or parts >= (22, 12, 0))


def probe_node() -> int:
    # 只消费固定的版本输出，不把路径或外部异常回显到诊断报告。
    try:
        result = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return 2
    return 0 if result.returncode == 0 and supported_node_version(result.stdout.strip()) else 2


def _terminate(process: subprocess.Popen[bytes]) -> None:
    # 超时必须清理 uv/npm 拉起的整个进程树，否则后台测试可能继续访问资源。
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def run_checks(checks: Sequence[Check], *, timeout: int) -> list[Result]:
    # 拒绝空计划、重名与前向依赖，避免任务漏配或循环依赖被当作成功。
    if not checks or timeout <= 0:
        raise ValueError("invalid_check_plan")
    known: set[str] = set()
    for check in checks:
        if not check.command or check.name in known or not set(check.requires) <= known:
            raise ValueError("invalid_check_plan")
        known.add(check.name)
    results: list[Result] = []
    statuses: dict[str, Status] = {}
    for check in checks:
        if any(statuses[name] != "passed" for name in check.requires):
            result = Result(check.name, "blocked", "prerequisite_not_passed")
        elif not check.cwd.is_dir():
            result = Result(check.name, "blocked", "working_directory_unavailable")
        else:
            result = _run_check(check, timeout)
        results.append(result)
        statuses[check.name] = result.status
        print(f"{result.name}: {result.status} ({result.reason})", flush=True)
    return results


def _run_check(check: Check, timeout: int) -> Result:
    # Windows 通过 npm.cmd 调用，避免 PowerShell 执行策略；不启用 shell=True。
    executable = shutil.which(check.command[0])
    if executable is None:
        return Result(check.name, "blocked", "command_unavailable")
    environment = dict(os.environ)
    environment.update(check.environment)
    try:
        with subprocess.Popen(
            [executable, *check.command[1:]],
            cwd=check.cwd,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        ) as process:
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _terminate(process)
                return Result(check.name, "failed", "timeout")
    except OSError:
        return Result(check.name, "blocked", "command_unavailable")
    diagnostics = None
    if check.summary_path is not None:
        try:
            diagnostics = read_test_summary(check.summary_path)
        except (OSError, ValueError, TypeError):
            return Result(check.name, "failed", "invalid_or_missing_summary", code)
        if diagnostics["status"] != "passed" and code == 0:
            return Result(check.name, "failed", "summary_not_passed", code, diagnostics)
    if code == 0:
        return Result(check.name, "passed", "completed", code, diagnostics)
    if check.preflight:
        return Result(check.name, "blocked", "environment_not_ready", code)
    return Result(check.name, "failed", "nonzero_exit", code, diagnostics)


def read_test_summary(path: Path) -> dict[str, object]:
    # 二次白名单校验确保即使产物损坏或被覆盖，原文也不会进入最终报告。
    if path.stat().st_size > 1_000_000:
        raise ValueError("summary_too_large")
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "status",
        "collected",
        "passed",
        "failed",
        "skipped",
        "collection_errors",
        "failures",
    }
    if not isinstance(payload, dict):
        raise ValueError("invalid_summary")
    # JSON 边界先保留未知值，随后逐字段校验，避免把未验证结构宣称为业务类型。
    payload = cast(dict[str, Any], payload)
    if set(payload) != required:
        raise ValueError("invalid_summary")
    if payload["schema_version"] != 1 or payload["status"] not in {"passed", "failed"}:
        raise ValueError("invalid_summary")
    for key in ("collected", "passed", "failed", "skipped", "collection_errors"):
        if type(payload[key]) is not int or payload[key] < 0:
            raise ValueError("invalid_summary")
    failures = payload["failures"]
    if not isinstance(failures, list):
        raise ValueError("invalid_summary")
    failures = cast(list[Any], failures)
    for failure in failures:
        if not isinstance(failure, dict):
            raise ValueError("invalid_summary")
        failure = cast(dict[str, Any], failure)
        if set(failure) != {"test", "phase"}:
            raise ValueError("invalid_summary")
        if failure["phase"] not in {"setup", "call", "teardown", "collection"}:
            raise ValueError("invalid_summary")
        identifier = failure["test"]
        if not isinstance(identifier, str) or (
            identifier != "redacted_test"
            and (
                not re.fullmatch(r"[A-Za-z0-9_/-]+\.py(?:::[A-Za-z_][A-Za-z0-9_]*)*", identifier)
                or identifier.startswith("/")
                or ".." in identifier.split("/")
            )
        ):
            raise ValueError("invalid_summary")
    if payload["status"] == "passed" and (
        payload["passed"] <= 0 or payload["failed"] or payload["collection_errors"]
    ):
        raise ValueError("invalid_summary")
    return cast(dict[str, object], payload)


def exit_code(results: Sequence[Result]) -> int:
    # failed 优先于 blocked；零检查同样不能返回成功。
    if any(result.status == "failed" for result in results):
        return 1
    if not results or any(result.status == "blocked" for result in results):
        return 2
    return 0


def write_report(path: Path, mode: str, component: str, results: Sequence[Result]) -> None:
    # 仅保存结构化元数据，不保存命令参数、环境、异常或外部输出。
    status = {0: "passed", 1: "failed", 2: "blocked"}[exit_code(results)]
    payload = {
        "schema_version": 2,
        "mode": mode,
        "component": component,
        "status": status,
        "scope": "mock_ui_only" if mode == "e2e" else mode,
        "checks": [asdict(result) for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_checks(mode: str, component: str, root: Path) -> list[Check]:
    # 预检与检查计划集中定义；CI 只选档位，不另复制质量命令。
    backend = root / "backend"
    frontend = root / "frontend"
    python = sys.executable
    npm = "npm.cmd" if os.name == "nt" else "npm"
    safe_environment = {
        "APP_ENV": "test",
        "DEEPSEEK_API_KEY": "",
        "UV_CACHE_DIR": str(root / ".tmp" / "quality-uv-cache"),
        "PYTHONUTF8": "1",
        # 防止 shell 的 --collect-only/-k/-m 悄悄缩小固定验收范围。
        "PYTEST_ADDOPTS": "",
    }
    checks: list[Check] = []
    run_id = uuid4().hex
    artifacts = root / ".tmp" / "quality"

    def add(
        name: str,
        command: tuple[str, ...],
        cwd: Path,
        requires: tuple[str, ...] = (),
        *,
        preflight: bool = False,
        environment: dict[str, str] | None = None,
        summary_path: Path | None = None,
    ) -> None:
        checks.append(
            Check(
                name,
                command,
                cwd,
                requires,
                safe_environment | (environment or {}),
                preflight,
                summary_path,
            )
        )

    add(
        "python-3.12",
        (python, "-c", "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 2)"),
        root,
        preflight=True,
    )
    if component in {"all", "backend"} and mode != "e2e":
        add("uv", ("uv", "--version"), root, preflight=True)
        add(
            "backend-dependencies",
            ("uv", "sync", "--locked", "--check", "--offline"),
            backend,
            ("uv", "python-3.12"),
            preflight=True,
        )
        ready = ("backend-dependencies",)
        if mode in {"doctor", "full", "http-e2e"}:
            add(
                "test-database",
                (python, "-m", "scripts.check_test_database"),
                backend,
                ready,
                preflight=True,
            )
            add("docker-compose", ("docker", "compose", "version"), root, preflight=True)
        if mode in {"quick", "full"}:
            add(
                "backend-format",
                (python, "-m", "ruff", "format", "--check", "--no-cache", "."),
                backend,
                ready,
            )
            add("backend-lint", (python, "-m", "ruff", "check", "--no-cache", "."), backend, ready)
            add(
                "tooling-format",
                (
                    python,
                    "-m",
                    "ruff",
                    "format",
                    "--check",
                    "--no-cache",
                    "--config",
                    "pyproject.toml",
                    "../scripts",
                ),
                backend,
                ready,
            )
            add(
                "tooling-lint",
                (
                    python,
                    "-m",
                    "ruff",
                    "check",
                    "--no-cache",
                    "--config",
                    "pyproject.toml",
                    "../scripts",
                ),
                backend,
                ready,
            )
            add("backend-types", (python, "-m", "pyright"), backend, ready)
            add(
                "architecture",
                (
                    python,
                    "-m",
                    "scripts.check_architecture",
                    "--output",
                    str(artifacts / f"architecture-{run_id}.json"),
                ),
                backend,
                ready,
            )
            test_args = ("-m", "not database and not compose") if mode == "quick" else ()
            test_ready = ready if mode == "quick" else (*ready, "test-database", "docker-compose")
            add(
                "backend-tests",
                (
                    python,
                    "-m",
                    "pytest",
                    "-q",
                    "-ra",
                    "-p",
                    "scripts.pytest_summary",
                    "--quality-summary",
                    str(artifacts / f"pytest-{run_id}.json"),
                    "--basetemp",
                    str(root / ".tmp" / "pytest" / uuid4().hex),
                    "-o",
                    f"cache_dir={root / '.tmp' / 'pytest-cache'}",
                    *test_args,
                ),
                backend,
                test_ready,
                summary_path=artifacts / f"pytest-{run_id}.json",
            )
            add("migration-heads", (python, "-m", "alembic", "heads"), backend, ready)
        if mode in {"quick", "full", "eval"}:
            add(
                "offline-evaluation",
                (
                    python,
                    "-m",
                    "scripts.evaluate_research",
                    "--output",
                    str(artifacts / f"research-adapter-{run_id}.json"),
                ),
                backend,
                ready,
            )
            add(
                "research-flows",
                (
                    python,
                    "-m",
                    "scripts.evaluate_research_flows",
                    "--output",
                    str(artifacts / f"research-flows-{run_id}.json"),
                ),
                backend,
                ready,
            )
    if component in {"all", "frontend"} and mode != "eval":
        add(
            "node",
            (python, str(root / "scripts" / "verify.py"), "--probe-node"),
            frontend,
            preflight=True,
        )
        add("npm", (npm, "--version"), frontend, preflight=True)
        add(
            "frontend-dependencies",
            (npm, "ls", "--depth=0"),
            frontend,
            ("node", "npm"),
            preflight=True,
        )
        ready = ("frontend-dependencies",)
        if mode in {"doctor", "e2e", "http-e2e"}:
            browser_check = (
                "const { chromium } = require('@playwright/test');"
                "const fs = require('node:fs');"
                "process.exit(fs.existsSync(chromium.executablePath())?0:2)"
            )
            add("chromium", ("node", "-e", browser_check), frontend, ready, preflight=True)
        if mode in {"quick", "full"}:
            add("frontend-lint", (npm, "run", "lint"), frontend, ready)
            add("frontend-types", (npm, "run", "typecheck"), frontend, ready)
            add(
                "frontend-tests",
                (npm, "run", "test", "--", "--run", "--reporter=dot"),
                frontend,
                ready,
            )
            if mode == "full":
                add("frontend-build", (npm, "run", "build"), frontend, ready)
        if mode == "e2e":
            add(
                "mock-e2e",
                (npm, "run", "test:e2e"),
                frontend,
                (*ready, "chromium"),
                environment={"CI": "1", "VITE_DATA_MODE": "mock"},
            )
        if mode == "http-e2e":
            add(
                "http-database-e2e",
                (npm, "run", "test:e2e:http"),
                frontend,
                (*ready, "chromium", "backend-dependencies", "test-database"),
                environment={"CI": "1", "HTTP_E2E_PYTHON": python},
            )
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    # 每个入口都回报最终退出码；报告写入失败同样不能被当作验收成功。
    parser = argparse.ArgumentParser(description="固定质量检查；失败详情请按开发文档单独复现。")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("doctor", "quick", "full", "eval", "e2e", "http-e2e"),
        default="full",
    )
    parser.add_argument("--component", choices=("all", "backend", "frontend"), default="all")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=int, default=900, help="每条检查的秒数上限")
    parser.add_argument("--probe-node", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.probe_node:
        return probe_node()
    if (
        args.timeout <= 0
        or (args.mode == "eval" and args.component == "frontend")
        or (args.mode == "e2e" and args.component == "backend")
        or (args.mode == "http-e2e" and args.component != "all")
    ):
        parser.error("incompatible mode/component or invalid timeout")
    if args.mode in {"quick", "full"}:
        # pytest 的 --basetemp 只创建最后一层；先建立父目录确保全新检出可运行。
        try:
            (ROOT / ".tmp" / "pytest").mkdir(parents=True, exist_ok=True)
        except OSError:
            print("pytest-temporary-directory: blocked (directory_unavailable)", flush=True)
            return 2
    try:
        (ROOT / ".tmp" / "quality").mkdir(parents=True, exist_ok=True)
    except OSError:
        print("quality-artifacts: blocked (directory_unavailable)", flush=True)
        return 2
    results = run_checks(build_checks(args.mode, args.component, ROOT), timeout=args.timeout)
    if args.report is not None:
        try:
            write_report(args.report, args.mode, args.component, results)
        except OSError:
            print("report: failed (report_unwritable)", flush=True)
            return 1
    code = exit_code(results)
    print(f"verification: { {0: 'passed', 1: 'failed', 2: 'blocked'}[code] }", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
