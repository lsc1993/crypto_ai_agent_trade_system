from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """PostgreSQL 持久化模型的共同元数据。"""
