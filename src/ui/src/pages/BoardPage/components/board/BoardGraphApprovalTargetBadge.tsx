import { formatNumber } from "@/core/utils/LocaleFormat";
import Badge from "@/components/base/Badge";
import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import HoverCard from "@/components/base/HoverCard";
import IconComponent from "@/components/base/IconComponent";
import { GraphApprovalRequestModel } from "@/core/models";
import { EGraphApprovalScopeTable, EGraphApprovalStatus } from "@/core/models/GraphApprovalRequestModel";
import { cn } from "@/core/utils/ComponentUtils";
import { useTranslation } from "react-i18next";
import { useGraphApprovalSummary, useGraphApprovalTitle } from "./GraphApprovalUtils";

interface IBoardGraphApprovalTargetBadgeProps {
    projectUID: string;
    scopeTable: EGraphApprovalScopeTable;
    scopeUID: string;
    className?: string;
}

function BoardGraphApprovalTargetBadge({ projectUID, scopeTable, scopeUID, className }: IBoardGraphApprovalTargetBadgeProps) {
    const [t] = useTranslation();
    const pendingApprovals = GraphApprovalRequestModel.Model.useModels((approval) => {
        return (
            approval.project_uid === projectUID &&
            approval.status === EGraphApprovalStatus.Pending &&
            approval.scope_table === scopeTable &&
            approval.scope_uid === scopeUID
        );
    });
    const pendingCount = pendingApprovals.length;

    if (!pendingCount) {
        return null;
    }

    const label = pendingCount > 99 ? "99+" : `${pendingCount}`;
    const pendingLabel = t("bot.{count} pending approvals", { count: pendingCount });

    return (
        <HoverCard.Root openDelay={120} closeDelay={80}>
            <HoverCard.Trigger asChild>
                <span
                    className={cn(
                        "inline-flex h-5 min-w-5 cursor-help items-center justify-center gap-1 rounded-full bg-destructive px-1.5",
                        "text-[10px] font-bold leading-none text-destructive-foreground shadow",
                        className
                    )}
                    title={pendingLabel}
                    aria-label={pendingLabel}
                    data-graph-approval-target-badge={`${scopeTable}:${scopeUID}`}
                    onPointerDown={(event) => event.stopPropagation()}
                >
                    <IconComponent icon="circle-alert" size="3" strokeWidth="3" />
                    <span>{label}</span>
                </span>
            </HoverCard.Trigger>
            <HoverCard.Content className="w-80 p-3" side="top" align="start">
                <BoardGraphApprovalTargetPreview approvals={pendingApprovals} />
            </HoverCard.Content>
        </HoverCard.Root>
    );
}

interface IBoardGraphApprovalTargetPreviewProps {
    approvals: GraphApprovalRequestModel.TModel[];
}

function BoardGraphApprovalTargetPreview({ approvals }: IBoardGraphApprovalTargetPreviewProps) {
    const [t, i18n] = useTranslation();
    const visibleApprovals = approvals.slice(0, 4);
    const hiddenCount = approvals.length - visibleApprovals.length;

    return (
        <Flex direction="col" gap="2">
            <Flex items="center" gap="1.5">
                <IconComponent icon="hand" size="3.5" className="text-primary" />
                <Box textSize="xs" weight="semibold">
                    {t("bot.Pending approvals")}
                </Box>
                <Badge variant="secondary" className="ml-auto px-2 py-0 text-[11px]">
                    {formatNumber(approvals.length, i18n.language)}
                </Badge>
            </Flex>
            <Flex direction="col" gap="1.5">
                {visibleApprovals.map((approval) => (
                    <BoardGraphApprovalTargetPreviewItem key={approval.uid} approval={approval} />
                ))}
            </Flex>
            {hiddenCount > 0 && (
                <Box textSize="xs" className="text-muted-foreground">
                    {t("bot.{count} more in Bots", { count: hiddenCount })}
                </Box>
            )}
        </Flex>
    );
}

interface IBoardGraphApprovalTargetPreviewItemProps {
    approval: GraphApprovalRequestModel.TModel;
}

function BoardGraphApprovalTargetPreviewItem({ approval }: IBoardGraphApprovalTargetPreviewItemProps) {
    const [t] = useTranslation();
    const originType = approval.useField("origin_type");
    const scopeTable = approval.useField("scope_table");
    const permission = approval.useField("permission");
    const title = useGraphApprovalTitle(approval, t("bot.Approval request"));
    const summary = useGraphApprovalSummary(approval);

    return (
        <Box className="rounded-md border bg-background/70 p-2">
            <Flex items="center" gap="1.5" wrap={true} className="mb-1">
                <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                    {t(`bot.approvalOriginTypes.${originType}`, { defaultValue: originType })}
                </Badge>
                <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                    {t(`bot.target_tables.${scopeTable}`, { defaultValue: scopeTable })}
                </Badge>
                {permission && (
                    <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                        {t(`bot.approvalPermissions.${permission}`, { defaultValue: permission })}
                    </Badge>
                )}
            </Flex>
            <Box textSize="xs" weight="semibold" className="break-words leading-snug">
                {title}
            </Box>
            {summary && (
                <Box textSize="xs" className="mt-1 line-clamp-2 break-words text-muted-foreground">
                    {summary}
                </Box>
            )}
        </Box>
    );
}

export default BoardGraphApprovalTargetBadge;
