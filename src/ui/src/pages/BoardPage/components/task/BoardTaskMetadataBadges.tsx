import Badge from "@/components/base/Badge";
import Flex from "@/components/base/Flex";
import { formatTaskMetadataValue, hasTaskMetadata, parseTaskMetadata } from "@/core/constants/TaskMetadata";
import { MetadataModel } from "@/core/models";
import { cn } from "@/core/utils/ComponentUtils";
import { memo } from "react";
import { useTranslation } from "react-i18next";

interface IBoardTaskMetadataBadgesProps {
    cardUID: string;
    className?: string;
    compact?: bool;
}

const BoardTaskMetadataBadges = memo(({ cardUID, className, compact = false }: IBoardTaskMetadataBadgesProps) => {
    const metadataRecord = MetadataModel.Model.useModel(cardUID, [cardUID]);

    if (!metadataRecord || metadataRecord.type !== "card") {
        return null;
    }

    return <BoardTaskMetadataBadgesInner metadataRecord={metadataRecord} className={className} compact={compact} />;
});

interface IBoardTaskMetadataBadgesInnerProps {
    metadataRecord: MetadataModel.TModel;
    className?: string;
    compact: bool;
}

function BoardTaskMetadataBadgesInner({ metadataRecord, className, compact }: IBoardTaskMetadataBadgesInnerProps): React.JSX.Element | null {
    const metadata = metadataRecord.useField("metadata");
    const task = parseTaskMetadata(metadata);
    const [t] = useTranslation();

    if (!hasTaskMetadata(task)) {
        return null;
    }

    const badges = [
        !!task.type && {
            key: "type",
            label: formatTaskMetadataValue(task.type),
            variant: "secondary" as const,
        },
        !!task.assignedAgent && {
            key: "agent",
            label: formatTaskMetadataValue(task.assignedAgent),
            variant: "outline" as const,
        },
        !!task.riskLevel && {
            key: "risk",
            label: `${t("card.Risk")}: ${formatTaskMetadataValue(task.riskLevel)}`,
            variant: task.riskLevel === "high" ? ("destructive" as const) : task.riskLevel === "low" ? ("success" as const) : ("outline" as const),
        },
        !!task.verification?.status && {
            key: "verification",
            label: `${t("card.Verification")}: ${formatTaskMetadataValue(task.verification.status)}`,
            variant:
                task.verification.status === "passed"
                    ? ("success" as const)
                    : task.verification.status === "failed"
                      ? ("destructive" as const)
                      : ("secondary" as const),
        },
        !compact &&
            !!task.run?.status && {
                key: "run",
                label: `${t("card.Run")}: ${formatTaskMetadataValue(task.run.status)}`,
                variant: task.run.status === "failed" ? ("destructive" as const) : ("outline" as const),
            },
        !compact &&
            !!task.prUrl && {
                key: "pr",
                label: "PR",
                variant: "outline" as const,
            },
        !compact &&
            !!task.suggestions.length && {
                key: "suggestions",
                label: `${t("card.Suggestions")}: ${task.suggestions.length}`,
                variant: "secondary" as const,
            },
    ].filter(Boolean);

    if (!badges.length) {
        return null;
    }

    return (
        <Flex items="center" gap="1" wrap className={cn("min-w-0", className)}>
            {badges.map(
                (badge) =>
                    !!badge && (
                        <Badge
                            key={`board-task-metadata-badge-${metadataRecord.uid}-${badge.key}`}
                            variant={badge.variant}
                            className="max-w-full truncate px-1.5 py-0 text-[10px] font-medium leading-5"
                            title={badge.label}
                        >
                            {badge.label}
                        </Badge>
                    )
            )}
        </Flex>
    );
}

BoardTaskMetadataBadges.displayName = "Board.TaskMetadataBadges";

export default BoardTaskMetadataBadges;
