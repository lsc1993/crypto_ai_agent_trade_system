# 验证 checkpoint 连接串适配不同 PostgreSQL 驱动。
# asyncpg URL 转换为 checkpoint 可用形式，已有 psycopg URL 保持不变。
# 转换使用秘密类型，不能在日志中泄露连接信息。
from pydantic import SecretStr

from app.shared.database import checkpoint_connection_string


def test_checkpoint_connection_string_converts_asyncpg_without_logging_secret() -> None:
    value = SecretStr("postgresql+asyncpg://user:password@localhost:5432/research")

    result = checkpoint_connection_string(value)

    assert result == "postgresql://user:password@localhost:5432/research"


def test_checkpoint_connection_string_preserves_psycopg_url() -> None:
    value = SecretStr("postgresql://user:password@localhost:5432/research")

    assert checkpoint_connection_string(value) == value.get_secret_value()
