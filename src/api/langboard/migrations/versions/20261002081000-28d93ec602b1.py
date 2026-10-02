"""Seed a small multilingual global label catalog without replacing user definitions."""

from datetime import datetime, timezone
import sqlalchemy as sa
from alembic import op
from langboard_shared.core.types import SnowflakeID


revision = "28d93ec602b1"
down_revision = "17c82db591a0"
branch_labels = None
depends_on = None

# Labels describe work type, never workflow state, priority, assignment, or authorization.
DEFAULT_LABELS = (
    (
        "#EF4444",
        ("Bug", "버그", "不具合", "缺陷"),
        (
            "An existing behavior fails to meet its expected result; record reproduction and verification.",
            "기존 동작이 기대 결과와 다른 문제입니다. 재현 조건과 수정 검증을 기록합니다.",
            "既存の動作が期待する結果と異なる問題。再現条件と修正の検証を記録します。",
            "现有行为未达到预期结果；记录复现条件与修复验证。",
        ),
    ),
    (
        "#8B5CF6",
        ("Feature", "기능", "機能", "功能"),
        (
            "A new capability or deliverable; define the intended outcome and acceptance criteria.",
            "새로운 기능이나 결과물을 추가합니다. 목표 결과와 수용 기준을 정의합니다.",
            "新しい機能や成果物の追加。目標と受け入れ基準を定義します。",
            "新增能力或交付物；明确目标结果与验收标准。",
        ),
    ),
    (
        "#0EA5E9",
        ("Improvement", "개선", "改善", "改进"),
        (
            "Improve the usability, quality, efficiency, or performance of an existing capability.",
            "기존 기능의 사용성·품질·효율·성능을 개선합니다.",
            "既存機能の使いやすさ、品質、効率、性能を改善します。",
            "改进现有能力的易用性、质量、效率或性能。",
        ),
    ),
    (
        "#14B8A6",
        ("Documentation", "문서", "ドキュメント", "文档"),
        (
            "Create or update reusable instructions, specifications, decisions, or knowledge.",
            "재사용 가능한 안내·명세·의사결정·지식을 작성하거나 갱신합니다.",
            "再利用可能な手順、仕様、意思決定、知識を作成または更新します。",
            "创建或更新可复用的指南、规范、决策记录或知识。",
        ),
    ),
    (
        "#F97316",
        ("Security", "보안", "セキュリティ", "安全"),
        (
            "Address security, privacy, or access-control concerns; this label does not grant permission.",
            "보안·개인정보·접근 제어 관련 사항을 다룹니다. 이 라벨은 권한을 부여하지 않습니다.",
            "セキュリティ、プライバシー、アクセス制御の課題。このラベルは権限を付与しません。",
            "处理安全、隐私或访问控制事项；此标签不授予权限。",
        ),
    ),
    (
        "#64748B",
        ("Maintenance", "유지보수", "保守", "维护"),
        (
            "Routine upkeep, dependency updates, cleanup, or operational maintenance.",
            "정기 점검·의존성 갱신·정리·운영 유지보수 작업입니다.",
            "定期点検、依存関係の更新、整理、運用保守の作業。",
            "日常检查、依赖更新、清理或运行维护工作。",
        ),
    ),
    (
        "#06B6D4",
        ("Frontend", "프론트엔드", "フロントエンド", "前端"),
        (
            "Client-facing UI, interaction, accessibility, presentation, and client-side performance.",
            "사용자 화면·상호작용·접근성·표현 및 클라이언트 성능에 관한 작업입니다.",
            "利用者向け画面、操作、アクセシビリティ、表示、クライアント性能の作業。",
            "面向用户的界面、交互、无障碍、展示及客户端性能工作。",
        ),
    ),
    (
        "#6366F1",
        ("Backend", "백엔드", "バックエンド", "后端"),
        (
            "Server APIs, business rules, authorization, persistence, and background processing.",
            "서버 API·업무 규칙·인가·데이터 영속성·백그라운드 처리에 관한 작업입니다.",
            "サーバーAPI、業務規則、認可、データ永続化、バックグラウンド処理の作業。",
            "服务端 API、业务规则、授权、数据持久化及后台处理工作。",
        ),
    ),
    (
        "#A855F7",
        ("Contract", "컨트랙트", "開発契約", "开发契约"),
        (
            "Development contracts between components or repositories: API and event schemas, types, invariants, "
            "errors, versioning, compatibility, and generated specifications. Record producers, consumers, and "
            "contract tests. This is not a legal or commercial agreement.",
            "컴포넌트·저장소 사이의 개발 계약입니다. API·이벤트 스키마, 타입, 불변 조건, 오류 규약, "
            "버전·호환성 및 생성 명세를 다루며 생산자·소비자·계약 테스트를 기록합니다. 법률·상거래 계약을 뜻하지 않습니다.",
            "コンポーネントやリポジトリ間の開発契約。API・イベントスキーマ、型、不変条件、エラー規約、"
            "バージョン、互換性、生成仕様を扱い、提供側・利用側・契約テストを記録します。法的・商取引契約ではありません。",
            "组件或仓库之间的开发契约：API 与事件模式、类型、不变量、错误约定、版本、兼容性及生成规范。"
            "记录生产方、消费方和契约测试；不表示法律或商业合同。",
        ),
    ),
    (
        "#D946EF",
        ("Assembly", "어셈블리", "アセンブリ", "集成装配"),
        (
            "Compose and integrate components into a deployable solution: packaging, configuration, dependencies, "
            "GitOps deployment definitions, and runtime wiring. Keep ownership and end-to-end acceptance explicit.",
            "컴포넌트를 배포 가능한 솔루션으로 조립·통합합니다. 패키징·설정·의존성·GitOps 배포 정의·런타임 연결을 "
            "다루며 소유 경계와 종단 검증 기준을 명시합니다.",
            "コンポーネントを配備可能なソリューションへ統合する作業。パッケージ、設定、依存関係、GitOps配備定義、"
            "実行時接続を扱い、所有境界と総合検証基準を明示します。",
            "将组件组装集成为可部署的解决方案，涉及打包、配置、依赖、GitOps 部署定义和运行时连接。"
            "明确所有权边界及端到端验收标准。",
        ),
    ),
    (
        "#3B82F6",
        ("Question", "질문", "質問", "问题咨询"),
        (
            "A clarification, unanswered question, or decision input; record the question, evidence, and answer.",
            "확인할 사항·미해결 질문·의사결정에 필요한 정보입니다. 질문·근거·답변을 기록합니다.",
            "確認事項、未回答の質問、意思決定に必要な情報。質問、根拠、回答を記録します。",
            "待澄清事项、未解答的问题或决策所需信息；记录问题、依据与回答。",
        ),
    ),
    (
        "#10B981",
        ("Money", "돈", "お金", "资金"),
        (
            "Monetary amounts, budgets, costs, payments, settlements, or accounting. State currency and calculation "
            "basis. Use Pricing for rate or billing-plan definitions. This label never authorizes a payment.",
            "금액·예산·비용·지급·정산·회계에 관한 작업입니다. 통화와 산정 근거를 명시합니다. "
            "단가·요금제 정의는 Pricing 라벨을 사용합니다. 이 라벨은 결제를 승인하지 않습니다.",
            "金額、予算、費用、支払、精算、会計の作業。通貨と計算根拠を明示します。"
            "単価・料金プラン定義はPricingを使用します。このラベルは支払を承認しません。",
            "金额、预算、成本、支付、结算或会计工作。明确币种与计算依据。"
            "费率或计费方案定义使用 Pricing；此标签不批准付款。",
        ),
    ),
    (
        "#F59E0B",
        ("Pricing", "요금", "料金", "费用"),
        (
            "Prices, unit rates, fees, billing plans, metered usage, or charge calculations. Define units, "
            "effective dates, and billing rules; actual payment or settlement work also uses Money.",
            "가격·단가·수수료·요금제·사용량 계량·청구액 산정에 관한 작업입니다. 단위·적용일·청구 규칙을 정의하며 "
            "실제 지급·정산 작업에는 Money 라벨도 사용합니다.",
            "価格、単価、手数料、料金プラン、使用量計測、請求額計算の作業。単位、適用日、請求規則を定義し、"
            "実際の支払・精算にはMoneyも使用します。",
            "价格、单价、手续费、计费方案、用量计量或收费计算工作。定义单位、生效日期与计费规则；"
            "实际支付或结算也使用 Money。",
        ),
    ),
)

DEFAULT_EMOJI = dict(
    zip(
        (names[0] for _, names, _ in DEFAULT_LABELS),
        ("🐛", "✨", "🛠️", "📚", "🛡️", "🔧", "🖥️", "⚙️", "📜", "🧩", "❓", "💰", "🧾"),
        strict=True,
    )
)

global_label = sa.table(
    "global_label",
    sa.column("id", sa.BigInteger()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
    sa.column("name", sa.String()),
    sa.column("color", sa.String()),
    sa.column("description", sa.String()),
    sa.column("emoji", sa.String()),
    sa.column("translations", sa.JSON()),
)


def _rows_to_insert(existing_names: list[str]) -> list[dict]:
    existing = {name.strip().casefold() for name in existing_names}
    now = datetime.now(timezone.utc)
    return [
        {
            "id": int(SnowflakeID()),
            "created_at": now,
            "updated_at": now,
            "name": names[0],
            "color": color,
            "description": descriptions[0],
            "emoji": DEFAULT_EMOJI[names[0]],
            "translations": {
                language: {"name": name, "description": description}
                for language, name, description in zip(("en", "ko", "ja", "zh"), names, descriptions, strict=True)
            },
        }
        for color, names, descriptions in DEFAULT_LABELS
        if names[0].casefold() not in existing
    ]


def seed_defaults() -> None:
    names = list(op.get_bind().execute(sa.select(global_label.c.name)).scalars())
    rows = _rows_to_insert(names)
    if rows:
        op.bulk_insert(global_label, rows)


def upgrade() -> None:
    op.add_column("global_label", sa.Column("emoji", sa.String(), nullable=False, server_default=""))
    seed_defaults()


def downgrade() -> None:
    """Retain definitions and references; remove only the added display field."""
    op.drop_column("global_label", "emoji")
