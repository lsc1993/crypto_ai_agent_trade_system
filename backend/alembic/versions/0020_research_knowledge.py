# 建立版本化关键词知识库：文档、不可变版本、GIN 词项分块与请求幂等记录。
# 本迁移只新增前向表和索引，不迁移旧报告、不回写真实知识库、不发布任何用户资料。
# 版本正文、分块集合和文档删除由触发器保护；发布只允许改变状态列，历史引用不删除。
# 0020 尚未合并或应用到业务库；复审 P1 修复在首次合并前补齐分块 INSERT 防护。
"""Versioned keyword research knowledge tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020_research_knowledge"
down_revision: str | None = "0019_strategy_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序创建知识表、约束、GIN 索引和不可变触发器。
def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("access", sa.String(16), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state_version >= 0", name="ck_knowledge_document_version"),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200",
            name="ck_knowledge_document_title",
        ),
        sa.CheckConstraint(
            "char_length(scope) BETWEEN 1 AND 64",
            name="ck_knowledge_document_scope",
        ),
        sa.CheckConstraint("access = 'workspace'", name="ck_knowledge_document_access"),
    )
    op.create_index(
        "ix_knowledge_documents_workspace_created",
        "knowledge_documents",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "knowledge_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_documents.id", name="fk_knowledge_versions_document"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("source", sa.String(500), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("access", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("first_available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("declared_published_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('draft','published')", name="ck_knowledge_version_state"),
        sa.CheckConstraint(
            "(state = 'draft' AND state_version = 0 AND published_at IS NULL) OR "
            "(state = 'published' AND state_version >= 1 AND published_at IS NOT NULL)",
            name="ck_knowledge_version_generation",
        ),
        sa.CheckConstraint(
            "octet_length(text) BETWEEN 1 AND 262144",
            name="ck_knowledge_version_text_size",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200",
            name="ck_knowledge_version_title",
        ),
        sa.CheckConstraint(
            "char_length(source) BETWEEN 1 AND 500",
            name="ck_knowledge_version_source",
        ),
        sa.CheckConstraint(
            "char_length(scope) BETWEEN 1 AND 64",
            name="ck_knowledge_version_scope",
        ),
        sa.CheckConstraint("access = 'workspace'", name="ck_knowledge_version_access"),
        sa.CheckConstraint(
            "char_length(text_sha256) = 64 AND char_length(sha256) = 64",
            name="ck_knowledge_version_sha",
        ),
        sa.CheckConstraint("chunk_count >= 1", name="ck_knowledge_version_chunks"),
        sa.CheckConstraint(
            "declared_published_at IS NULL OR declared_published_at <= first_available_at",
            name="ck_knowledge_version_declared_time",
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR published_at >= first_available_at",
            name="ck_knowledge_version_published_time",
        ),
    )
    op.create_index(
        "ix_knowledge_versions_workspace_state_published",
        "knowledge_versions",
        ["workspace_id", "state", "published_at"],
    )
    op.create_index(
        "ix_knowledge_versions_document",
        "knowledge_versions",
        ["document_id", "created_at"],
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_versions.id", name="fk_knowledge_chunks_version"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("terms", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("title_terms", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.UniqueConstraint(
            "version_id",
            "chunk_index",
            name="uq_knowledge_chunks_version_index",
        ),
        sa.CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunk_index"),
        sa.CheckConstraint("octet_length(text) >= 1", name="ck_knowledge_chunk_text"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_knowledge_chunk_sha"),
    )
    op.create_index(
        "ix_knowledge_chunks_terms",
        "knowledge_chunks",
        ["terms"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_knowledge_chunks_title_terms",
        "knowledge_chunks",
        ["title_terms"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_knowledge_chunks_workspace_version",
        "knowledge_chunks",
        ["workspace_id", "version_id"],
    )
    op.create_table(
        "knowledge_index_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('import','publish','archive')",
            name="ck_knowledge_index_request_action",
        ),
        sa.CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_knowledge_index_request_sha",
        ),
    )

    # 版本正文只允许草稿一次性迁移为 published；已发布行、正文列和删除都拒绝。
    op.execute(
        """
        CREATE FUNCTION reject_knowledge_version_body_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'knowledge versions are immutable';
            END IF;
            IF OLD.state = 'published' THEN
                RAISE EXCEPTION 'knowledge versions are immutable';
            END IF;
            IF NEW.state <> 'published'
                OR NEW.state_version < 1
                OR NEW.published_at IS NULL
            THEN
                RAISE EXCEPTION 'knowledge versions are immutable';
            END IF;
            IF NEW.document_id IS DISTINCT FROM OLD.document_id
                OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
                OR NEW.title IS DISTINCT FROM OLD.title
                OR NEW.source IS DISTINCT FROM OLD.source
                OR NEW.scope IS DISTINCT FROM OLD.scope
                OR NEW.access IS DISTINCT FROM OLD.access
                OR NEW.text IS DISTINCT FROM OLD.text
                OR NEW.text_sha256 IS DISTINCT FROM OLD.text_sha256
                OR NEW.sha256 IS DISTINCT FROM OLD.sha256
                OR NEW.chunk_count IS DISTINCT FROM OLD.chunk_count
                OR NEW.first_available_at IS DISTINCT FROM OLD.first_available_at
                OR NEW.declared_published_at IS DISTINCT FROM OLD.declared_published_at
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'knowledge versions are immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_knowledge_versions_immutable
        BEFORE UPDATE OR DELETE ON knowledge_versions
        FOR EACH ROW EXECUTE FUNCTION reject_knowledge_version_body_mutation();
        """
    )

    # 分块是导入事务的冻结快照；发布/归档不需要改写分块，任何 UPDATE/DELETE 都拒绝。
    op.execute(
        """
        CREATE FUNCTION reject_knowledge_chunk_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'knowledge chunks are immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_knowledge_chunks_immutable
        BEFORE UPDATE OR DELETE ON knowledge_chunks
        FOR EACH ROW EXECUTE FUNCTION reject_knowledge_chunk_mutation();
        """
    )

    # 分块只允许在父版本仍为草稿时插入，且必须对应该版本正文的固定切片。
    # FOR KEY SHARE 与 publish 的版本行 FOR UPDATE 冲突：发布先持锁时，追加等待后看到
    # published 被拒绝；追加先持锁时，发布等待其提交并核对完整分块集合。
    # 900/1000 与 research/knowledge/indexing.py 的 CHUNK_SIZE/CHUNK_OVERLAP 固定契约一致。
    op.execute(
        """
        CREATE FUNCTION guard_knowledge_chunk_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_state text;
            parent_workspace uuid;
            parent_text text;
            parent_chunk_count integer;
            expected_text text;
        BEGIN
            EXECUTE format(
                'SELECT state, workspace_id, text, chunk_count '
                'FROM %I.knowledge_versions WHERE id = $1 FOR KEY SHARE',
                TG_TABLE_SCHEMA
            )
            INTO parent_state, parent_workspace, parent_text, parent_chunk_count
            USING NEW.version_id;

            -- EXECUTE 不保证按 SELECT INTO 语义设置 FOUND；state 非空，用其作为存在哨兵。
            IF parent_state IS NULL THEN
                RAISE EXCEPTION 'knowledge chunk parent missing';
            END IF;
            IF parent_state <> 'draft' THEN
                RAISE EXCEPTION 'knowledge chunks are immutable';
            END IF;
            IF NEW.workspace_id <> parent_workspace THEN
                RAISE EXCEPTION 'knowledge chunk workspace mismatch';
            END IF;
            IF NEW.chunk_index < 0 OR NEW.chunk_index >= parent_chunk_count THEN
                RAISE EXCEPTION 'knowledge chunk index out of range';
            END IF;
            expected_text := substr(parent_text, NEW.chunk_index * 900 + 1, 1000);
            IF NEW.text IS DISTINCT FROM expected_text THEN
                RAISE EXCEPTION 'knowledge chunk text mismatch';
            END IF;
            IF NEW.sha256 <> encode(sha256(convert_to(NEW.text, 'UTF8')), 'hex') THEN
                RAISE EXCEPTION 'knowledge chunk hash mismatch';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_knowledge_chunks_insert_guard
        BEFORE INSERT ON knowledge_chunks
        FOR EACH ROW EXECUTE FUNCTION guard_knowledge_chunk_insert();
        """
    )

    # 文档允许归档和元数据更新，但禁止删除，以保留版本与历史引用链。
    op.execute(
        """
        CREATE FUNCTION reject_knowledge_document_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'knowledge documents are immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_knowledge_documents_no_delete
        BEFORE DELETE ON knowledge_documents
        FOR EACH ROW EXECUTE FUNCTION reject_knowledge_document_delete();
        """
    )


# 前向迁移明确拒绝回退，避免删除已发布知识版本和用户历史引用。
def downgrade() -> None:
    raise NotImplementedError("版本化知识库迁移不可逆，禁止删除历史引用")
