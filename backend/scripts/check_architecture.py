# 用标准库 AST 检查研究、治理内核和风控的直接依赖边界，不导入待检模块。
# 规则覆盖静态导入及可识别的动态导入；计算出的模块名会拒绝，但这不是任意
# Python 运行期安全证明：反射、间接包装器、重导出和依赖传递仍需审查与运行测试。
# 报告只包含安全相对路径、行号、固定规则码和计数，不记录源码、模块参数或异常文本。
from __future__ import annotations

import argparse
import ast
import json
import os
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from importlib.util import resolve_name
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("agent", "governance", "risk")
REQUIRED_FILES = (
    "src/app/agent/__init__.py",
    "src/app/agent/service.py",
    "src/app/agent/graph.py",
    "src/app/agent/technical/plan_service.py",
    "src/app/governance/__init__.py",
    "src/app/governance/runtime.py",
    "src/app/governance/audit.py",
    "src/app/risk/__init__.py",
    "src/app/risk/engine.py",
)
TRADE_MODULES = ("app.execution", "app.risk", "app.strategy", "app.paper_trading")
RULES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "agent": (("ARCH001", TRADE_MODULES),),
    "governance": (
        ("ARCH002", TRADE_MODULES),
        (
            "ARCH003",
            (
                "httpx",
                "requests",
                "aiohttp",
                "urllib.request",
                "http.client",
                "urllib3",
                "socket",
                "subprocess",
                "playwright",
                "selenium",
                "ccxt",
                "os.system",
                "os.popen",
            ),
        ),
        ("ARCH004", ("app.infrastructure.persistence", "sqlalchemy", "alembic")),
    ),
    "risk": (
        (
            "ARCH005",
            (
                "app.agent",
                "openai",
                "anthropic",
                "langchain",
                "langchain_core",
                "langchain_openai",
                "langgraph",
                "litellm",
            ),
        ),
    ),
}
SAFE_COMPONENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.py)?\Z")


@dataclass(frozen=True, order=True)
class Finding:
    # 不存储原异常或源码；行号 0 表示文件/扫描层错误。
    path: str
    line: int
    rule: str


@dataclass(frozen=True)
class ArchitectureReport:
    # 不完整扫描也会产生 finding，所以 passed 不会把零扫描当作成功。
    files_scanned: int
    findings: tuple[Finding, ...]

    @property
    def passed(self) -> bool:
        # 对调用者只提供门禁结论，不能据此推断运行期权限安全。
        return self.files_scanned > 0 and not self.findings

    def to_json(self) -> str:
        # 构造固定 schema，禁止把异常对象或动态诊断数据透传到产物。
        return (
            json.dumps(
                {
                    "status": "passed" if self.passed else "failed",
                    "files_scanned": self.files_scanned,
                    "findings": [asdict(item) for item in self.findings],
                },
                indent=2,
            )
            + "\n"
        )


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _safe_path(path: Path, root: Path) -> str:
    # 不解析链接后再展示绝对位置，也不允许文件名控制终端或 JSON 内容。
    relative = path.relative_to(root)
    if not all(SAFE_COMPONENT.fullmatch(part) for part in relative.parts):
        return "src/app"
    return relative.as_posix()


def _string(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _argument(call: ast.Call, position: int, name: str) -> ast.expr | None:
    if len(call.args) > position:
        return call.args[position]
    return next((item.value for item in call.keywords if item.arg == name), None)


class _DependencyVisitor(ast.NodeVisitor):
    # 保守收集导入别名，不执行代码或推断任意赋值；别名重绑定可能仍会触发拒绝。
    # 全树预收集也让嵌套函数和条件导入无法仅凭书写顺序避开明确动态导入检查。
    def __init__(self, scope: str, path: str, tree: ast.Module) -> None:
        self.rules = RULES[scope]
        self.path = path
        parts = path.removeprefix("src/").removesuffix(".py").split("/")
        self.package = ".".join(parts[:-1])
        self.findings: set[Finding] = set()
        self.aliases: dict[str, set[str]] = {"__import__": {"builtins.__import__"}}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    local = item.asname or item.name.split(".")[0]
                    target = item.name if item.asname else item.name.split(".")[0]
                    self.aliases.setdefault(local, set()).add(target)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                for item in node.names:
                    target = f"{node.module}.{item.name}"
                    self.aliases.setdefault(item.asname or item.name, set()).add(target)

    def _record(self, line: int, rule: str) -> None:
        self.findings.add(Finding(self.path, line, rule))

    def _check(self, module: str, line: int) -> None:
        for rule, prefixes in self.rules:
            if any(_matches(module, prefix) for prefix in prefixes):
                self._record(line, rule)

    def _resolve(self, name: str, package: str | None, line: int) -> str | None:
        try:
            return resolve_name(name, package) if name.startswith(".") else name
        except (ImportError, ValueError):
            self._record(line, "ARCH006")
            return None

    def _from(self, module: str, names: Sequence[str], line: int) -> None:
        self._check(module, line)
        for name in names:
            if name == "*":
                # 受保护父包的星号导入无法判定暴露的子模块，按无法分析拒绝。
                if any(
                    _matches(prefix, module) for _, prefixes in self.rules for prefix in prefixes
                ):
                    self._record(line, "ARCH006")
            else:
                self._check(f"{module}.{name}", line)

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            self._check(item.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = self._resolve("." * node.level + (node.module or ""), self.package, node.lineno)
        if module is not None:
            self._from(module, [item.name for item in node.names], node.lineno)

    def _targets(self, node: ast.expr) -> set[str]:
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id, set())
        if isinstance(node, ast.Attribute):
            return {f"{target}.{node.attr}" for target in self._targets(node.value)}
        return set()

    def visit_Call(self, node: ast.Call) -> None:
        for target in self._targets(node.func):
            self._check(target, node.lineno)
            if target in {"importlib.import_module", "builtins.__import__"}:
                self._dynamic_import(node, target)
        self.generic_visit(node)

    def _dynamic_import(self, node: ast.Call, target: str) -> None:
        # 仅解释明确字符串以及标准 fromlist/level 参数。未解析表达式不猜测安全。
        if any(item.arg is None for item in node.keywords) or any(
            isinstance(item, ast.Starred) for item in node.args
        ):
            self._record(node.lineno, "ARCH006")
            return
        name = _string(_argument(node, 0, "name"))
        if name is None:
            self._record(node.lineno, "ARCH006")
            return
        if target == "importlib.import_module":
            package_node = _argument(node, 1, "package")
            package = (
                self.package
                if isinstance(package_node, ast.Name) and package_node.id == "__package__"
                else _string(package_node)
            )
            module = self._resolve(name, package, node.lineno)
            if module is not None:
                self._check(module, node.lineno)
            return
        level_node = _argument(node, 4, "level")
        level = 0
        if level_node is not None:
            if not isinstance(level_node, ast.Constant) or type(level_node.value) is not int:
                self._record(node.lineno, "ARCH006")
                return
            level = level_node.value
            if level < 0:
                self._record(node.lineno, "ARCH006")
                return
        if level:
            # 自定义 globals 可改变相对导入基准，不能套用当前源码所属包推断。
            globals_node = _argument(node, 1, "globals")
            if not (
                isinstance(globals_node, ast.Call)
                and isinstance(globals_node.func, ast.Name)
                and globals_node.func.id == "globals"
                and not globals_node.args
                and not globals_node.keywords
            ):
                self._record(node.lineno, "ARCH006")
                return
        module = self._resolve("." * level + name, self.package, node.lineno)
        if module is None:
            return
        self._check(module, node.lineno)
        fromlist = _argument(node, 3, "fromlist")
        if fromlist is None:
            return
        if not isinstance(fromlist, (ast.List, ast.Tuple)):
            self._record(node.lineno, "ARCH006")
            return
        names = [_string(item) for item in fromlist.elts]
        if any(item is None for item in names):
            self._record(node.lineno, "ARCH006")
        self._from(module, [item for item in names if item is not None], node.lineno)


def scan_architecture(root: Path = BACKEND_ROOT) -> ArchitectureReport:
    # 输入为后端目录；仅扫描三个指定边界，关键模块缺失、读取失败或链接均失败。
    # 不跟随符号链接/junction，避免误扫范围外源码以及把未扫描目录当成通过。
    findings: set[Finding] = set()
    files_scanned = 0
    for name in REQUIRED_FILES:
        if not (root / name).is_file():
            findings.add(Finding(name, 0, "ARCH100"))
    for scope in SCOPES:
        directory = root / "src/app" / scope
        if any(
            part.is_symlink() or part.is_junction()
            for part in (root, root / "src", root / "src/app", directory)
        ):
            findings.add(Finding(f"src/app/{scope}", 0, "ARCH102"))
            continue
        found = 0

        def walk_error(_: OSError) -> None:
            findings.add(Finding(f"src/app/{scope}", 0, "ARCH103"))

        for parent, folders, names in os.walk(directory, onerror=walk_error, followlinks=False):
            for folder in folders[:]:
                child = Path(parent) / folder
                if child.is_symlink() or child.is_junction():
                    findings.add(Finding(_safe_path(child, root), 0, "ARCH102"))
                    folders.remove(folder)
            for name in sorted(names):
                if not name.endswith(".py"):
                    continue
                found += 1
                path = Path(parent) / name
                safe_path = _safe_path(path, root)
                if path.is_symlink() or safe_path == "src/app":
                    findings.add(Finding(safe_path, 0, "ARCH102"))
                    continue
                try:
                    tree = ast.parse(path.read_bytes(), filename="source.py")
                except SyntaxError as exc:
                    findings.add(Finding(safe_path, exc.lineno or 0, "ARCH101"))
                    continue
                except (OSError, ValueError, UnicodeError):
                    findings.add(Finding(safe_path, 0, "ARCH103"))
                    continue
                files_scanned += 1
                visitor = _DependencyVisitor(scope, safe_path, tree)
                visitor.visit(tree)
                findings.update(visitor.findings)
        if not found:
            findings.add(Finding(f"src/app/{scope}", 0, "ARCH100"))
    return ArchitectureReport(files_scanned, tuple(sorted(findings)))


def main(argv: Sequence[str] | None = None) -> int:
    # CLI 可供质量入口调用；输出失败时也使用固定码，不回显目标路径或异常。
    parser = argparse.ArgumentParser(description="Check static research architecture boundaries.")
    parser.add_argument("--root", type=Path, default=BACKEND_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = scan_architecture(args.root)
    serialized = report.to_json()
    if args.output is not None:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8")
        except (OSError, ValueError):
            print("ARCH105")
            return 1
    print(serialized, end="")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
