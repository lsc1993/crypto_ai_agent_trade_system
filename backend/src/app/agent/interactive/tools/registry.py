# 构造不可变工具目录：按名称排序、验证 Schema、计算完整目录指纹并提供模型可见投影。
# 目录只来自服务端登记；模型文本、知识片段或远端说明不能追加工具、提升版本或改变范围。
# 本模块不调用处理器、不访问数据库/网络，也不导入治理、交易、风控或执行服务。
from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import cast

from app.agent.interactive.context import ModelTool, ToolCatalogReader
from app.agent.interactive.tools.contracts import (
    RegisteredTool,
    ToolContractError,
    ToolHandler,
)
from app.agent_runs.segments import ExecutionContext
from app.shared.agent_types import JsonValue, sha256_json


# 工具目录是启动时冻结的只读集合；同一次运行只能使用与 ExecutionContext 匹配的目录。
class ToolRegistry(ToolCatalogReader):
    def __init__(self, tools: Iterable[RegisteredTool]) -> None:
        bounded = tuple(tools)
        names = tuple(tool.name for tool in bounded)
        if len(set(names)) != len(names):
            raise ToolContractError("duplicate_tool", "工具名称不能重复登记")
        self._tools = tuple(sorted(bounded, key=lambda tool: tool.name))
        self._model_tools = tuple(_model_tool(tool) for tool in self._tools)
        self._catalog_sha256 = sha256_json(
            cast(JsonValue, [tool.model_dump(mode="json") for tool in self._model_tools])
        )
        # 目录条目指纹覆盖输出 Schema、能力和范围；版本字符串把它带入模型可见投影。

    @property
    def tools(self) -> tuple[RegisteredTool, ...]:
        return self._tools

    @property
    def catalog_sha256(self) -> str:
        return self._catalog_sha256

    def get(self, name: str) -> RegisteredTool | None:
        return next((tool for tool in self._tools if tool.name == name), None)

    def model_tools(self) -> tuple[ModelTool, ...]:
        return self._model_tools

    def model_version(self, name: str) -> str | None:
        return next(
            (tool.version for tool in self._model_tools if tool.name == name),
            None,
        )

    # ContextBuilder 的只读目录端口；目录指纹由调用方按同一投影重新计算。
    async def authorized(self, context: ExecutionContext) -> tuple[ModelTool, ...]:
        _ = context
        return self._model_tools

    # 验证处理函数与目录一一对应；缺少实现或多余处理函数都 fail-closed。
    def bind_handlers(self, handlers: Mapping[str, ToolHandler]) -> dict[str, ToolHandler]:
        names = {tool.name for tool in self._tools}
        if set(handlers) != names:
            raise ToolContractError("handler_mismatch", "工具目录与处理器集合不一致")
        bound: dict[str, ToolHandler] = {}
        for name, handler in handlers.items():
            if handler.tool.name != name:
                raise ToolContractError("handler_mismatch", "处理器声明的工具名称不一致")
            expected = self.get(name)
            if expected is None or handler.tool != expected:
                raise ToolContractError("handler_mismatch", "处理器工具描述与目录不一致")
            bound[name] = handler
        return bound


# 模型可见版本由基础版本和完整目录条目哈希组成；任一 Schema/范围/超时变化都会改变指纹。
def _model_tool(tool: RegisteredTool) -> ModelTool:
    entry = tool.catalog_entry()
    digest = sha256_json(cast(JsonValue, entry))
    version = f"{tool.version}_{digest[:12]}"
    return ModelTool(
        name=tool.name,
        version=version,
        description=tool.description,
        input_schema=copy.deepcopy(tool.input_schema),
    )


# 名称别名便于上层按“目录”语义引用，不产生第二套实现。
ToolCatalog = ToolRegistry


__all__ = ["ToolCatalog", "ToolRegistry"]
