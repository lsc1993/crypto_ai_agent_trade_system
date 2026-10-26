# 定义所有 SQLAlchemy 表模型共享的 DeclarativeBase。
# 模型导入时向共同 metadata 注册表；仓储使用这些定义构造 SQL。
# 真实数据库结构由 Alembic 迁移管理，声明基类本身不建表。
from sqlalchemy.orm import DeclarativeBase


# 全部 ORM 模型的公共元数据容器；不附带业务校验或自动迁移逻辑。
class Base(DeclarativeBase):
    """PostgreSQL 持久化模型的共同元数据。"""
