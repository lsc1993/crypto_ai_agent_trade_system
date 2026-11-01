# 验证 AST 门禁对真实依赖、扫描完整性和安全报告的约束。
# 合成源码只写入 pytest 临时树，不导入或执行被检查代码；真实仓库另作回归。
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FILES = (
    "src/app/agent/__init__.py",
    "src/app/agent/service.py",
    "src/app/agent/graph.py",
    "src/app/agent/technical/plan_service.py",
    "src/app/harness/__init__.py",
    "src/app/harness/runtime.py",
    "src/app/harness/audit.py",
    "src/app/risk/__init__.py",
    "src/app/risk/engine.py",
)


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    # 显式列出各受保护边界的入口，避免空树被当作通过。
    for name in REQUIRED_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic source\n", encoding="utf-8")
    return tmp_path


def _run(root: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.check_architecture",
            "--root",
            str(root),
            "--output",
            str(output),
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_gate_cli_checks_real_repository_and_writes_report(tmp_path: Path) -> None:
    # 缺失命令、零扫描或错误退出码都不能伪装成架构通过。
    output = tmp_path / "architecture.json"
    result = _run(BACKEND_ROOT, output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["files_scanned"] > 20
    assert report["findings"] == []


@pytest.mark.parametrize(
    ("module", "source", "rule"),
    [
        ("agent/probe.py", "import app.execution.engine as e", "ARCH001"),
        ("agent/probe.py", "import app as package\npackage.execution.Engine()", "ARCH001"),
        ("agent/probe.py", "from app.risk import engine", "ARCH001"),
        ("agent/probe.py", "from app import strategy as s", "ARCH001"),
        ("agent/probe.py", "from .. import paper_trading", "ARCH001"),
        ("agent/technical/probe.py", "from ...execution import engine", "ARCH001"),
        ("agent/technical/__init__.py", "from ... import risk", "ARCH001"),
        ("agent/probe.py", "if True:\n    import app.execution", "ARCH001"),
        ("agent/probe.py", "import json, app.execution.engine", "ARCH001"),
        ("harness/probe.py", "from app import strategy", "ARCH002"),
        ("harness/probe.py", "from ..paper_trading import engine", "ARCH002"),
        ("harness/probe.py", "from urllib import request", "ARCH003"),
        ("harness/probe.py", "import httpx as transport", "ARCH003"),
        ("harness/probe.py", "from requests.sessions import Session", "ARCH003"),
        ("harness/probe.py", "from app.infrastructure import persistence", "ARCH004"),
        ("harness/probe.py", "from sqlalchemy import create_engine", "ARCH004"),
        ("harness/probe.py", "from os import system as run\nrun('unused')", "ARCH003"),
        ("harness/probe.py", "import os as runtime\nruntime.system('unused')", "ARCH003"),
        ("risk/probe.py", "from app.agent.model import ResearchModel", "ARCH005"),
        ("risk/probe.py", "from app import agent", "ARCH005"),
        ("risk/probe.py", "from openai import OpenAI", "ARCH005"),
        ("risk/probe.py", "import langgraph.graph", "ARCH005"),
        (
            "agent/probe.py",
            "import importlib as loader\nloader.import_module('app.execution.engine')",
            "ARCH001",
        ),
        (
            "agent/probe.py",
            "from importlib import import_module as load\nload(name='app.risk')",
            "ARCH001",
        ),
        (
            "agent/probe.py",
            "import importlib\nimportlib.import_module('..execution', __package__)",
            "ARCH001",
        ),
        (
            "agent/probe.py",
            "import importlib\nimportlib.import_module('.risk', package='app')",
            "ARCH001",
        ),
        ("agent/probe.py", "__import__('app.execution')", "ARCH001"),
        (
            "agent/probe.py",
            "from builtins import __import__ as load\nload('app', fromlist=['risk'])",
            "ARCH001",
        ),
        ("agent/probe.py", "import builtins as b\nb.__import__('app.strategy')", "ARCH001"),
        (
            "agent/probe.py",
            "__import__('risk', globals(), fromlist=('engine',), level=2)",
            "ARCH001",
        ),
        (
            "agent/probe.py",
            "__import__('risk', {'__package__': 'app'}, fromlist=['engine'], level=1)",
            "ARCH006",
        ),
        (
            "agent/probe.py",
            "__import__('app', fromlist=names)",
            "ARCH006",
        ),
        (
            "agent/probe.py",
            "__import__('app', **{'fromlist': ['risk']})",
            "ARCH006",
        ),
        ("agent/probe.py", "__import__('app', *options)", "ARCH006"),
        (
            "agent/probe.py",
            "import importlib\nimportlib.import_module('...risk', 'app')",
            "ARCH006",
        ),
        ("agent/probe.py", "from ....risk import engine", "ARCH006"),
        ("agent/probe.py", "from app import *", "ARCH006"),
        ("agent/probe.py", "import importlib\nimportlib.import_module(target)", "ARCH006"),
    ],
)
def test_forbidden_dependencies_fail_without_executing_source(
    source_tree: Path, module: str, source: str, rule: str
) -> None:
    # 每种写法都运行同一个 CLI，直接验证违规导致非零并归入固定规则码。
    path = source_tree / "src/app" / module
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source + "\n", encoding="utf-8")
    output = source_tree / "report.json"
    result = _run(source_tree, output)
    assert result.returncode == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert any(item["rule"] == rule for item in report["findings"])
    assert all(set(item) == {"path", "line", "rule"} for item in report["findings"])


def test_comments_strings_and_legitimate_contracts_do_not_trigger_gate(source_tree: Path) -> None:
    # 依赖取自语法节点而非文本；合法研究 HTTP 和风控策略契约保留。
    (source_tree / "src/app/agent/service.py").write_text(
        "# import app.execution\nvalue = 'from app import risk'\nimport httpx\n",
        encoding="utf-8",
    )
    (source_tree / "src/app/risk/engine.py").write_text(
        "from app.strategy.contracts import TradeIntent\n", encoding="utf-8"
    )
    (source_tree / "src/app/harness/runtime.py").write_text(
        "from app.agent.technical.worker import TechnicalPlanRunExecutor\n",
        encoding="utf-8",
    )
    assert _run(source_tree, source_tree / "report.json").returncode == 0


@pytest.mark.parametrize("failure", ["empty", "missing", "syntax", "encoding", "unsafe_path"])
def test_incomplete_scan_fails_with_only_safe_diagnostics(
    source_tree: Path, tmp_path: Path, failure: str
) -> None:
    # 不把源码、解析器异常、绝对路径或任意文件名写入诊断产物。
    if failure == "empty":
        source_tree = tmp_path / "empty"
        source_tree.mkdir()
    elif failure == "missing":
        (source_tree / "src/app/harness/audit.py").unlink()
    elif failure == "syntax":
        (source_tree / "src/app/agent/service.py").write_text(
            "SECRET_SENTINEL = (\n", encoding="utf-8"
        )
    elif failure == "encoding":
        (source_tree / "src/app/agent/service.py").write_bytes(b"\xffSECRET_SENTINEL")
    else:
        (source_tree / "src/app/agent/SECRET_SENTINEL bad.py").write_text(
            "import app.execution\n", encoding="utf-8"
        )
    output = source_tree / "report.json"
    result = _run(source_tree, output)
    assert result.returncode == 1
    serialized = output.read_text(encoding="utf-8")
    report = json.loads(serialized)
    assert report["status"] == "failed"
    assert report["findings"]
    assert "SECRET_SENTINEL" not in serialized + result.stdout + result.stderr
    assert str(source_tree) not in serialized + result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_output_write_error_is_safe_and_nonzero(source_tree: Path) -> None:
    # 目录不能作 JSON 文件，失败消息不能回显用户提供的目标路径。
    result = _run(source_tree, source_tree)
    assert result.returncode == 1
    assert "ARCH105" in result.stdout
    assert str(source_tree) not in result.stdout + result.stderr
