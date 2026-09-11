# Agent Report Validation Observability Design

## Goal

让格式校验失败的市场研究报告保留可审计、可展示的脱敏失败摘要，并在有限重试中向模型提供同样的摘要以便针对性纠正。

## Scope

系统仅保存和展示下列机器生成的元数据：最终失败尝试次数、校验问题数量、最多八个字段路径和去重后的错误类别。它不会保存模型原始响应、提示词、新闻全文、证据正文或凭证。

当模型返回 `model_invalid_response` 时，下一次格式重试会附加字段路径和错误类别。该附加内容只来自 Pydantic 校验错误的结构化位置和本地分类，不含被拒绝文本。

报告降级时，Agent 运行记录保存这份摘要。报告详情 API 对降级结果返回可空的 `validationFailure` 对象；成功报告和非格式类失败不返回摘要。前端将该对象转换为简洁的中文原因说明。

## Data Model

`agent_research_runs` 新增以下可空列：

- `model_validation_attempt_count`：最终失败前的模型格式尝试次数。
- `model_validation_issue_count`：最终响应的 Pydantic 问题数量。
- `model_validation_field_paths`：最多八个字段路径的 JSON 数组。
- `model_validation_error_categories`：去重、排序后的本地错误类别 JSON 数组。

字段只在 `model_invalid_response` 时写入。迁移为现有记录提供空值，因此不会重写或改变历史报告。

## Flow

```text
DeepSeek JSON -> Pydantic validation -> sanitized ModelOutputError
      | valid                              | invalid
      v                                    v
 completed report              retry with field/category summary
                                           |
                                      final failure
                                           v
                         degraded report + validation metadata
                                           v
                          detail API -> UI reason explanation
```

## Error Handling

字段路径与错误类别的上限继续由模型适配器控制。未知错误类别归入 `schema`。数据库、API 和前端将失败摘要视为可选；缺失字段时沿用现有的笼统降级提示，确保旧记录和非格式错误兼容。

## Verification

测试应证明：重试请求包含脱敏摘要且不含模型原文；最终格式失败被持久化并经 API 返回；历史或非格式失败不返回失败摘要；前端准确显示可用摘要。运行 Ruff、Pyright、后端 pytest 和前端相关测试。
