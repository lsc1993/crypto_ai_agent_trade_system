# pytest 的可选安全证据插件，仅由统一验证入口显式加载。
# 保留测试代码标识与计数，不保存参数值、异常、traceback、捕获输出或跳过原因。
# 零执行不可通过；产物写入失败也必须令进程失败，不能形成缺失证据的绿灯。
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


def safe_identifier(nodeid: str) -> str:
    # 参数化后缀可能含账户、证据或模型原文，整段丢弃而非尝试替换敏感关键字。
    parts = nodeid.split("[", 1)[0].replace("\\", "/").split("::")
    if not parts or not re.fullmatch(r"[A-Za-z0-9_/-]+\.py", parts[0]):
        return "redacted_test"
    if ".." in parts[0].split("/") or parts[0].startswith("/"):
        return "redacted_test"
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts[1:]):
        return "redacted_test"
    return "::".join(parts)


class SafeSummary:
    # 一次 pytest 运行使用一个实例；同一用例在 teardown 失败时不能仍被统计为通过。
    def __init__(self, path: Path) -> None:
        self.path = path
        self.collected = 0
        self.outcomes: dict[str, str] = {}
        self.failures: set[tuple[str, str]] = set()
        self.collection_errors = 0

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.collected = len(session.items)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.collection_errors += 1
            self.failures.add((safe_identifier(report.nodeid), "collection"))

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # 不访问 longrepr/capstdout/capstderr；nodeid 原值仅留作本进程内去重。
        if report.failed:
            self.outcomes[report.nodeid] = "failed"
            self.failures.add((safe_identifier(report.nodeid), report.when))
        elif self.outcomes.get(report.nodeid) != "failed":
            if report.when == "call" and report.passed:
                self.outcomes[report.nodeid] = "passed"
            elif report.skipped:
                self.outcomes[report.nodeid] = "skipped"

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        passed = sum(value == "passed" for value in self.outcomes.values())
        failed = sum(value == "failed" for value in self.outcomes.values())
        skipped = sum(value == "skipped" for value in self.outcomes.values())
        if exitstatus == 0 and passed + failed == 0:
            session.exitstatus = pytest.ExitCode.NO_TESTS_COLLECTED
        status = "passed" if session.exitstatus == 0 and not failed else "failed"
        payload = {
            "schema_version": 1,
            "status": status,
            "collected": self.collected,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "collection_errors": self.collection_errors,
            "failures": [{"test": test, "phase": phase} for test, phase in sorted(self.failures)],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError:
            # 不回显路径/异常；父验证器根据退出码报告失败。
            session.exitstatus = pytest.ExitCode.INTERNAL_ERROR


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--quality-summary", default=None, help="Write safe test identifiers and counts"
    )


def pytest_configure(config: pytest.Config) -> None:
    path: str | None = config.getoption("--quality-summary")
    if path:
        config.pluginmanager.register(SafeSummary(Path(path)), "quality-safe-summary")
