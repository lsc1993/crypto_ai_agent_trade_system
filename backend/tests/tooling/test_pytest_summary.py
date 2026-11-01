# 使用真实 pytest 子进程验证安全摘要，不保存原始异常或带值参数。
# 故意失败、语法错误、只收集和全跳过必须产生非成功状态。
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[2]


def run_case(tmp_path: Path, source: str, *extra: str) -> tuple[int, dict[str, Any]]:
    # 只替换测试根和进程环境；被测插件与 pytest 都实际运行。
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_case.py").write_text(source, encoding="utf-8")
    output = tmp_path / "safe.json"
    environment = dict(os.environ)
    environment.update(PYTHONPATH=str(BACKEND), PYTEST_ADDOPTS="")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "scripts.pytest_summary",
            "-q",
            "--quality-summary",
            str(output),
            "-c",
            "pytest.ini",
            *extra,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert output.is_file(), "safe pytest summary was not produced"
    return result.returncode, json.loads(output.read_text(encoding="utf-8"))


def test_failure_identifier_drops_parameter_values_and_exception(tmp_path: Path) -> None:
    code, report = run_case(
        tmp_path,
        """
import pytest
@pytest.mark.parametrize('value', ['PRIVATE_ACCOUNT_PAYLOAD'])
def test_private(value):
    raise RuntimeError('PRIVATE_MODEL_RESPONSE')
""",
    )
    assert code == 1
    assert report["status"] == "failed"
    assert report["failed"] == 1
    assert report["failures"] == [{"test": "test_case.py::test_private", "phase": "call"}]
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize(
    "source,extra",
    [
        ("def test_ok():\n    pass\n", ("--collect-only",)),
        ("import pytest\n@pytest.mark.skip(reason='PRIVATE')\ndef test_skip():\n    pass\n", ()),
        ("", ()),
    ],
)
def test_zero_execution_never_passes(tmp_path: Path, source: str, extra: tuple[str, ...]) -> None:
    code, report = run_case(tmp_path, source, *extra)
    assert code != 0
    assert report["status"] != "passed"
    assert report["passed"] == 0


def test_collection_error_is_reported_without_source(tmp_path: Path) -> None:
    code, report = run_case(tmp_path, "PRIVATE_BAD_SYNTAX !")
    assert code != 0
    assert report["collection_errors"] == 1
    assert report["failures"] == [{"test": "test_case.py", "phase": "collection"}]
    assert "PRIVATE" not in json.dumps(report)


def test_success_counts_executed_tests(tmp_path: Path) -> None:
    code, report = run_case(tmp_path, "def test_ok():\n    pass\n")
    assert code == 0
    assert report["status"] == "passed"
    assert report["collected"] == 1
    assert report["passed"] == 1
    assert report["failures"] == []
