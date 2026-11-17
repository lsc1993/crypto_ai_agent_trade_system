# MCP 基础设施包：固定端点登记、有界传输、官方 SDK 客户端和同进程只读服务。
# 具体类型分别位于 registry/transport/client/server；包入口不做重导出，避免装配期循环导入。
# 该包只承载本地研究工作台的只读 MCP 能力，不提供任意 URL、stdio、外部服务发现或交易接口。
