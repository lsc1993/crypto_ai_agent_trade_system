# 表模型集中导出入口；导入列出的模型向 Base.metadata 注册声明，__all__ 指定公开名称。
# 此处只说明包边界；具体公开名称以子模块导入或既有 __all__ 为准。
"""SQLAlchemy 持久化模型。"""

from app.infrastructure.persistence.models.agent_research import (
    AgentAnalysisRunRecord,
    AgentReportDetailRecord,
)
from app.infrastructure.persistence.models.harness import (
    HarnessAuditEventRecord,
    HarnessAuditRunRecord,
    HarnessEvaluationRecord,
)
from app.infrastructure.persistence.models.news import NewsItemRecord
from app.infrastructure.persistence.models.paper_trading import (
    PaperAccountRecord,
    PaperAccountValuationRecord,
    PaperAuditEventRecord,
    PaperFillRecord,
    PaperLedgerEntryRecord,
    PaperMarketSnapshotRecord,
    PaperOrderRecord,
    PaperPositionRecord,
)
from app.infrastructure.persistence.models.symbols import (
    ResearchNewsLinkRecord,
    ResearchSymbolEventRecord,
    ResearchSymbolRecord,
    ResearchSymbolSyncRunRecord,
)
from app.infrastructure.persistence.models.technical_reports import TechnicalReportRecord
from app.infrastructure.persistence.models.technical_runs import (
    TechnicalQueueRecord,
    TechnicalRequestRecord,
    TechnicalRunRecord,
)

__all__ = [
    "TechnicalQueueRecord",
    "TechnicalRequestRecord",
    "TechnicalRunRecord",
    "TechnicalReportRecord",
    "AgentAnalysisRunRecord",
    "AgentReportDetailRecord",
    "HarnessAuditEventRecord",
    "HarnessAuditRunRecord",
    "HarnessEvaluationRecord",
    "NewsItemRecord",
    "PaperAccountRecord",
    "PaperAccountValuationRecord",
    "PaperAuditEventRecord",
    "PaperFillRecord",
    "PaperLedgerEntryRecord",
    "PaperMarketSnapshotRecord",
    "PaperOrderRecord",
    "PaperPositionRecord",
    "ResearchNewsLinkRecord",
    "ResearchSymbolEventRecord",
    "ResearchSymbolRecord",
    "ResearchSymbolSyncRunRecord",
]
