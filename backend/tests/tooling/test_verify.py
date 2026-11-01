# 验证统一质量入口的真实进程行为，不运行项目全量检查。
# 临时脚本模拟工具成功、失败、超时和敏感输出，断言退出码与依赖阻断。
# 不依赖本机 Docker 或数据库；错误输出不能进入终端摘要或 JSON 报告。
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("quality_verify", PROJECT_ROOT / "scripts/verify.py")
assert SPEC is not None and SPEC.loader is not None
verify = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify
SPEC.loader.exec_module(verify)


# 命令失败不能被后续成功覆盖，同时与失败无关的检查仍须执行。
def test_failed_check_blocks_dependents_but_not_independent_checks(tmp_path: Path) -> None:
    completed = tmp_path / "completed"
    checks = [
        verify.Check("precheck", (sys.executable, "-c", "raise SystemExit(7)"), tmp_path),
        verify.Check(
            "dependent",
            (sys.executable, "-c", "raise SystemExit(0)"),
            tmp_path,
            requires=("precheck",),
        ),
        verify.Check(
            "independent",
            (sys.executable, "-c", f"from pathlib import Path; Path({str(completed)!r}).touch()"),
            tmp_path,
        ),
    ]
    results = verify.run_checks(checks, timeout=10)
    assert [result.status for result in results] == ["failed", "blocked", "passed"]
    assert results[0].returncode == 7
    assert completed.is_file()
    assert verify.exit_code(results) == 1


# 工具不存在是阻塞，不应伪造为成功或泄露操作系统错误。
def test_missing_executable_is_blocked(tmp_path: Path) -> None:
    results = verify.run_checks(
        [verify.Check("missing", ("missing-quality-tool-unique",), tmp_path)], timeout=10
    )
    assert results[0].status == "blocked"
    assert results[0].reason == "command_unavailable"
    assert verify.exit_code(results) == 2


# 已运行但超时的检查是失败；进程必须在限制后终止。
def test_timeout_fails_without_hanging(tmp_path: Path) -> None:
    results = verify.run_checks(
        [verify.Check("slow", (sys.executable, "-c", "import time; time.sleep(30)"), tmp_path)],
        timeout=1,
    )
    assert results[0].status == "failed"
    assert results[0].reason == "timeout"
    assert verify.exit_code(results) == 1


# 预检返回专用退出码 2 时应显示 blocked，测试失败的退出码 2 仍是 failed。
def test_only_declared_preflight_treats_exit_two_as_blocked(tmp_path: Path) -> None:
    command = (sys.executable, "-c", "raise SystemExit(2)")
    results = verify.run_checks(
        [
            verify.Check("doctor", command, tmp_path, preflight=True),
            verify.Check("tests", command, tmp_path),
        ],
        timeout=10,
    )
    assert [result.status for result in results] == ["blocked", "failed"]


# 报告不包含外部进程的任意 stdout/stderr，避免失败样本携带连接串或模型原文。
def test_child_output_is_not_exposed_in_console_or_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "PRIVATE_CONNECTION_AND_MODEL_PAYLOAD"
    results = verify.run_checks(
        [verify.Check("unsafe-output", (sys.executable, "-c", f"print({secret!r})"), tmp_path)],
        timeout=10,
    )
    report = tmp_path / "result.json"
    verify.write_report(report, "quick", "backend", results)
    assert secret not in capsys.readouterr().out
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["checks"][0]["name"] == "unsafe-output"
    assert secret not in report.read_text(encoding="utf-8")


# 缺失任务与非法依赖必须拒绝，防止配置失效后零检查仍显示通过。
def test_empty_plan_and_unknown_dependency_cannot_pass(tmp_path: Path) -> None:
    assert verify.exit_code([]) != 0
    with pytest.raises(ValueError):
        verify.run_checks([], timeout=10)
    with pytest.raises(ValueError):
        verify.run_checks(
            [verify.Check("x", (sys.executable,), tmp_path, requires=("unknown",))], timeout=10
        )


# Node 版本检查遵守 package.json 的范围边界，不能误接受旧 Node 22 或 Node 21。
@pytest.mark.parametrize(
    ("version", "accepted"),
    [
        ("20.18.9", False),
        ("20.19.0", True),
        ("21.9.0", False),
        ("22.11.0", False),
        ("22.12.0", True),
        ("24.0.0", True),
    ],
)
def test_node_engine_boundaries(version: str, accepted: bool) -> None:
    assert verify.supported_node_version(version) is accepted


# 默认完整模式不能悄悄变为快速验证；快速模式明确排除有外部前提的测试。
def test_modes_keep_database_and_mock_e2e_scope_explicit() -> None:
    full = verify.build_checks("full", "all", PROJECT_ROOT)
    quick = verify.build_checks("quick", "backend", PROJECT_ROOT)
    e2e = verify.build_checks("e2e", "frontend", PROJECT_ROOT)
    assert "test-database" in {check.name for check in full}
    assert "backend-format" in {check.name for check in full}
    assert "offline-evaluation" in {check.name for check in full}
    pytest_check = next(check for check in quick if check.name == "backend-tests")
    assert "not database and not compose" in pytest_check.command
    assert "test-database" not in {check.name for check in quick}
    playwright = next(check for check in e2e if check.name == "mock-e2e")
    assert playwright.environment["VITE_DATA_MODE"] == "mock"
    assert playwright.environment["CI"] == "1"


# 外部 shell 的 pytest 参数不能把完整验证改成只收集或筛选少量用例。
def test_gate_clears_inherited_pytest_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_deliberate_failure.py").write_text(
        "def test_must_execute():\n    assert False\n", encoding="utf-8"
    )
    checks = verify.build_checks("full", "backend", PROJECT_ROOT)
    configured = next(check for check in checks if check.name == "backend-tests")
    probe = verify.Check(
        "pytest-options-probe",
        (sys.executable, "-m", "pytest", "-q", "-c", str(tmp_path / "pytest.ini")),
        tmp_path,
        environment=configured.environment,
    )
    results = verify.run_checks([probe], timeout=10)
    assert results[0].returncode == 1
    assert verify.exit_code(results) == 1


# pytest 不会为 --basetemp 自动创建多层父目录；首次运行也必须可用。
def test_main_prepares_parent_for_isolated_pytest_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_probe.py").write_text(
        "def test_has_temporary_path(tmp_path):\n    (tmp_path / 'proof').touch()\n",
        encoding="utf-8",
    )
    base = tmp_path / ".tmp" / "pytest" / "first-run"

    def isolated_plan(*args: object) -> list[object]:
        return [
            verify.Check(
                "temporary-directory",
                (sys.executable, "-m", "pytest", "-q", "--basetemp", str(base)),
                tmp_path,
            )
        ]

    monkeypatch.setattr(verify, "build_checks", isolated_plan)
    assert verify.main(["quick", "--component", "backend"]) == 0
    assert list(base.rglob("proof"))


# 缺失或携带任意原文的证据文件不能让返回零的命令假绿或泄密。
def test_missing_or_unsafe_summary_fails_closed(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    check = verify.Check("tests", (sys.executable, "-c", "pass"), tmp_path, summary_path=summary)
    assert verify.exit_code(verify.run_checks([check], timeout=10)) == 1
    summary.write_text('{"raw_exception":"PRIVATE_PAYLOAD"}', encoding="utf-8")
    results = verify.run_checks([check], timeout=10)
    assert verify.exit_code(results) == 1
    assert "PRIVATE" not in repr(results)


# HTTP 验收必须同时依赖真实测试库和浏览器，不得静默落到 Mock 流程。
def test_http_e2e_plan_requires_real_backend_and_database() -> None:
    checks = verify.build_checks("http-e2e", "all", PROJECT_ROOT)
    check = next(check for check in checks if check.name == "http-database-e2e")
    assert "test-database" in check.requires
    assert "chromium" in check.requires
    assert "test:e2e:http" in check.command
    assert check.environment["HTTP_E2E_PYTHON"] == sys.executable
