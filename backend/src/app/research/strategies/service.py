# 组合策略目录与只读评估器，负责参数门禁、精确评估器查询和结果绑定校验。
# 服务不实现任何交易算法、不访问私有账户，也不把模型叙事当作评估来源。
# 缺少评估器或参数不合格时返回显式无候选状态，绝不静默改用其他策略。
from __future__ import annotations

from uuid import UUID

from pydantic import JsonValue

from app.research.evidence import EvidenceEpoch
from app.research.strategies.contracts import (
    StrategyApplicability,
    StrategyContractError,
    StrategyEvaluation,
    StrategyEvaluationStatus,
    StrategyEvaluatorError,
    StrategyIntegrityError,
    StrategyNotAvailableError,
    StrategyParameterError,
    StrategySchemaError,
    StrategyVersion,
    parameter_sha256,
    validate_parameters,
)
from app.research.strategies.ports import StrategyCatalog, StrategyEvaluator
from app.shared.agent_types import VersionRef


# 评估器注册表按 evaluator_id 精确查找；重复登记同一 ID 直接拒绝，避免启动顺序决定实现。
class StrategyEvaluatorRegistry:
    def __init__(self) -> None:
        self._evaluators: dict[str, StrategyEvaluator] = {}

    # 登记评估器并要求稳定 ID/版本；不执行策略文本或任意代码。
    def register(self, evaluator: StrategyEvaluator) -> None:
        evaluator_id = evaluator.evaluator_id.strip()
        version = evaluator.evaluator_version.strip()
        if not evaluator_id or not version:
            raise StrategyContractError("评估器必须有稳定 ID 和版本")
        if evaluator_id in self._evaluators:
            raise StrategyContractError("评估器 ID 不能重复登记")
        self._evaluators[evaluator_id] = evaluator

    # 精确查找；未登记返回 None，由服务输出 no_evaluator 而不是回退。
    def get(self, evaluator_id: str) -> StrategyEvaluator | None:
        return self._evaluators.get(evaluator_id)

    def evaluator_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._evaluators))


# 策略评估服务：目录负责发布内容，服务只按所选版本和已登记评估器执行。
class StrategyService:
    def __init__(
        self,
        *,
        catalog: StrategyCatalog,
        evaluators: StrategyEvaluatorRegistry | None = None,
    ) -> None:
        self._catalog = catalog
        self._evaluators = evaluators or StrategyEvaluatorRegistry()

    # 读取已发布版本，校验参数后调用精确评估器；输入先做隔离快照并重验完整性。
    async def evaluate(
        self,
        workspace_id: UUID,
        ref: VersionRef,
        parameters: dict[str, JsonValue],
        evidence: EvidenceEpoch,
    ) -> StrategyEvaluation:
        safe_evidence = evidence.validated_snapshot()
        strategy = await self._catalog.get_published(workspace_id, ref)
        strategy = strategy.validated_snapshot()
        if strategy.ref != ref:
            raise StrategyIntegrityError("目录返回的策略版本与请求引用不一致")
        if strategy.archived or strategy.archived_at is not None:
            raise StrategyNotAvailableError("策略已停用，不能执行新的评估")
        evaluator = self._evaluators.get(strategy.evaluator_id)
        evaluator_version = evaluator.evaluator_version if evaluator is not None else "unavailable"
        raw_parameter_sha = _safe_parameter_sha256(parameters)

        try:
            normalized = validate_parameters(strategy.parameter_schema, parameters)
        except (StrategyParameterError, StrategySchemaError):
            return StrategyEvaluation(
                strategy_ref=strategy.ref,
                evaluator_id=strategy.evaluator_id,
                evaluator_version=evaluator_version,
                parameters_sha256=raw_parameter_sha,
                evidence_sha256=safe_evidence.sha256,
                status=StrategyEvaluationStatus.INVALID_PARAMETERS,
                applicability=StrategyApplicability.UNKNOWN,
                reason_codes=("invalid_parameters",),
            )

        normalized_sha = parameter_sha256(normalized)
        if evaluator is None:
            return StrategyEvaluation(
                strategy_ref=strategy.ref,
                evaluator_id=strategy.evaluator_id,
                evaluator_version="unavailable",
                parameters_sha256=normalized_sha,
                evidence_sha256=safe_evidence.sha256,
                status=StrategyEvaluationStatus.NO_EVALUATOR,
                applicability=StrategyApplicability.UNKNOWN,
                reason_codes=("evaluator_unavailable",),
            )
        if evaluator.evaluator_id != strategy.evaluator_id:
            raise StrategyIntegrityError("评估器 ID 与所选策略不一致")

        try:
            evaluation = await evaluator.evaluate(strategy, normalized, safe_evidence)
        except StrategyEvaluatorError as error:
            return StrategyEvaluation(
                strategy_ref=strategy.ref,
                evaluator_id=strategy.evaluator_id,
                evaluator_version=evaluator.evaluator_version,
                parameters_sha256=normalized_sha,
                evidence_sha256=safe_evidence.sha256,
                status=StrategyEvaluationStatus.FAILED,
                applicability=StrategyApplicability.UNKNOWN,
                reason_codes=(error.code,),
            )
        _verify_evaluation(
            evaluation,
            strategy=strategy,
            evaluator_version=evaluator.evaluator_version,
            parameters_sha256=normalized_sha,
            evidence=safe_evidence,
        )
        return evaluation


# 结果校验必须覆盖版本、评估器、参数和证据；适配器不能把别家版本的结果冒充本次评估。
def _verify_evaluation(
    evaluation: StrategyEvaluation,
    *,
    strategy: StrategyVersion,
    evaluator_version: str,
    parameters_sha256: str,
    evidence: EvidenceEpoch,
) -> None:
    if evaluation.strategy_ref != strategy.ref:
        raise StrategyIntegrityError("评估结果的策略版本与所选版本不一致")
    if evaluation.evaluator_id != strategy.evaluator_id:
        raise StrategyIntegrityError("评估结果的评估器 ID 与所选策略不一致")
    if evaluation.evaluator_version != evaluator_version:
        raise StrategyIntegrityError("评估结果的评估器版本与登记版本不一致")
    if evaluation.parameters_sha256 != parameters_sha256:
        raise StrategyIntegrityError("评估结果的参数指纹与本次参数不一致")
    if evaluation.evidence_sha256 != evidence.sha256:
        raise StrategyIntegrityError("评估结果的证据指纹与本次证据不一致")


# 参数指纹可能遇到非 JSON 安全值；保留稳定失败指纹，不把异常文本或原值写入日志。
def _safe_parameter_sha256(parameters: dict[str, JsonValue]) -> str:
    try:
        return parameter_sha256(parameters)
    except TypeError:
        return parameter_sha256({"invalidParameters": True})


__all__ = ["StrategyEvaluatorRegistry", "StrategyService"]
