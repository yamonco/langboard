"""Install global workflow definitions without changing existing column policies."""

import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType
from langboard_shared.core.types import SafeDateTime, SnowflakeID


revision = "4afb6de824d3"
down_revision = "39ea4fd713c2"
branch_labels = None
depends_on = None


def builtin_rows():
    definitions = [
        (
            "backlog",
            ("Backlog", "백로그", "バックログ", "待办"),
            (
                "Untriaged or uncommitted work.",
                "분류하거나 착수 약속하지 않은 업무.",
                "未分類または未着手の業務。",
                "尚未分类或承诺开始的工作。",
            ),
            "#94A3B8",
            "conditional",
        ),
        (
            "ready",
            ("Ready", "준비", "準備完了", "就绪"),
            (
                "Owned and prepared work waiting to start.",
                "담당자가 정해지고 시작 준비를 마친 업무.",
                "担当者が決まり、開始準備が整った業務。",
                "已有负责人且准备好开始的工作。",
            ),
            "#84CC16",
            "conditional",
        ),
        (
            "active",
            ("Active", "진행 중", "進行中", "进行中"),
            (
                "Work currently being executed.",
                "현재 실제로 수행 중인 업무.",
                "現在実行中の業務。",
                "当前正在执行的工作。",
            ),
            "#3B82F6",
            "include",
        ),
        (
            "review",
            ("Review", "검토", "レビュー", "审核"),
            (
                "Work awaiting review or acceptance.",
                "검토 또는 인수를 기다리는 업무.",
                "レビューまたは受入確認を待つ業務。",
                "等待审核或验收的工作。",
            ),
            "#A855F7",
            "conditional",
        ),
        (
            "closed",
            ("Closed", "완료", "完了", "已完成"),
            (
                "Operationally completed work; verification remains a separate state.",
                "운영상 완료된 업무. 검증 상태는 별도로 유지한다.",
                "運用上完了した業務。検証状態は別に保持します。",
                "运营上已完成的工作；验证状态单独保留。",
            ),
            "#64748B",
            "exclude",
        ),
        (
            "reference",
            ("Reference", "참고자료", "参考資料", "参考资料"),
            (
                "Reference material excluded from the active work queue.",
                "실행 업무 큐에서 제외하는 참고자료.",
                "実行業務キューから除外する参考資料。",
                "不列入活动工作队列的参考资料。",
            ),
            "#14B8A6",
            "exclude",
        ),
    ]
    rows, used = [], set()
    now = SafeDateTime.now()
    for order, (key, names, descriptions, color, queue) in enumerate(definitions):
        for _ in range(32):
            identifier = int(SnowflakeID())
            if identifier not in used:
                used.add(identifier)
                break
        else:
            raise RuntimeError("Could not allocate unique workflow seed IDs")
        rows.append(
            dict(
                id=identifier,
                created_at=now,
                updated_at=now,
                key=key,
                name=names[0],
                description=descriptions[0],
                color=color,
                order=order,
                is_builtin=True,
                is_active=True,
                counts_as_completed=key == "closed",
                active_queue_policy=queue,
                overdue_policy="suppress" if key == "closed" else "normal",
                entry_effects=[],
                translations={
                    lang: {"name": name, "description": description}
                    for lang, name, description in zip(("en", "ko", "ja", "zh"), names, descriptions)
                },
            )
        )
    return rows


def upgrade():
    table = op.create_table(
        "workflow_stage_definition",
        sa.Column("id", SnowflakeIDType(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("counts_as_completed", sa.Boolean(), nullable=False),
        sa.Column("active_queue_policy", sa.String(), nullable=False),
        sa.Column("overdue_policy", sa.String(), nullable=False),
        sa.Column("entry_effects", sa.JSON(), nullable=False),
        sa.Column("translations", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_workflow_stage_definition_key", "workflow_stage_definition", ["key"], unique=True)
    op.bulk_insert(table, builtin_rows())


def downgrade():
    op.drop_table("workflow_stage_definition")
