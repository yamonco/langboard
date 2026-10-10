import { formatNumber } from "@/core/utils/LocaleFormat";
import Badge from "@/components/base/Badge";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Dialog from "@/components/base/Dialog";
import Drawer from "@/components/base/Drawer";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Input from "@/components/base/Input";
import ScrollArea from "@/components/base/ScrollArea";
import Toast from "@/components/base/Toast";
import BotLogList from "@/components/bots/BotLogList";
import BotScheduleList from "@/components/bots/BotScheduleList";
import BotTriggerConditionList from "@/components/bots/BotTriggerConditionList";
import UserAvatar from "@/components/UserAvatar";
import useApproveGraphApproval from "@/controllers/api/board/graphApprovals/useApproveGraphApproval";
import useGetGraphApprovals from "@/controllers/api/board/graphApprovals/useGetGraphApprovals";
import useRejectGraphApproval from "@/controllers/api/board/graphApprovals/useRejectGraphApproval";
import useToggleBotScopeFreeze from "@/controllers/api/shared/botScopes/useToggleBotScopeFreeze";
import useBoardGraphApprovalDeletedHandlers from "@/controllers/socket/board/graphApprovals/useBoardGraphApprovalDeletedHandlers";
import useBoardGraphApprovalRequestedHandlers from "@/controllers/socket/board/graphApprovals/useBoardGraphApprovalRequestedHandlers";
import useBoardGraphApprovalUpdatedHandlers from "@/controllers/socket/board/graphApprovals/useBoardGraphApprovalUpdatedHandlers";
import { DISABLE_DRAGGING_ATTR } from "@/constants";
import useHandleInteractOutside from "@/core/hooks/useHandleInteractOutside";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { useSocket } from "@/core/providers/SocketProvider";
import {
    BaseBotScheduleModel,
    BotDefaultScopeBranchModel,
    BotModel,
    Project,
    ProjectBotSchedule,
    ProjectBotScope,
    ProjectCard,
    ProjectCardBotSchedule,
    ProjectCardBotScope,
    ProjectColumn,
    ProjectColumnBotSchedule,
    ProjectColumnBotScope,
    GraphApprovalRequestModel,
} from "@/core/models";
import { EGraphApprovalOriginType, EGraphApprovalStatus } from "@/core/models/GraphApprovalRequestModel";
import * as BaseBotScopeModel from "@/core/models/botScopes/BaseBotScopeModel";
import { EBotTriggerCondition } from "@/core/models/botScopes/EBotTriggerCondition";
import { TBotScopeModel, TBotScopeModelName } from "@/core/models/ModelRegistry";
import { ProjectRole } from "@/core/models/roles";
import { TBotRelatedTargetTable } from "@/core/models/types/bot.related.type";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { cn } from "@/core/utils/ComponentUtils";
import { IBoardRelatedPageProps } from "@/pages/BoardPage/types";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useGraphApprovalSummary, useGraphApprovalTitle } from "./GraphApprovalUtils";

const BOARD_BOT_SCOPE_APPROVAL_ORIGIN_TYPES = new Set<EGraphApprovalOriginType>([
    EGraphApprovalOriginType.Trigger,
    EGraphApprovalOriginType.Schedule,
    EGraphApprovalOriginType.ManualScopeRun,
]);

export function isBoardBotScopeGraphApprovalOriginType(originType: EGraphApprovalOriginType): bool {
    return BOARD_BOT_SCOPE_APPROVAL_ORIGIN_TYPES.has(originType);
}

export type TBoardBotScopeTarget =
    | { target_table: "project"; target: Project.TModel }
    | { target_table: "project_column"; target: ProjectColumn.TModel }
    | { target_table: "card"; target: ProjectCard.TModel };

export interface IBoardBotScopeProps extends IBoardRelatedPageProps {
    isOpened: bool;
    setIsOpened: (isOpened: bool) => void;
}

interface IBoardBotScopeListProps {
    target: TBoardBotScopeTarget;
    className?: string;
}

interface IBoardBotScopeRow {
    botUID: string;
    bot: BotModel.TModel;
    botScope?: BaseBotScopeModel.TModel;
    hasScheduled: bool;
}

function BoardBotScope({ project, ...props }: IBoardBotScopeProps) {
    const currentUserRoleActions = project.useField("current_auth_role_actions");
    const { hasRoleAction } = useRoleActionFilter(currentUserRoleActions);
    const canEdit = hasRoleAction(ProjectRole.EAction.Update);

    if (!canEdit) {
        return null;
    }

    return <BoardBotScopeDisplay project={project} {...props} />;
}

function BoardBotScopeDisplay({ project, isOpened, setIsOpened }: IBoardBotScopeProps) {
    const { onInteractOutside, onPointerDownOutside } = useHandleInteractOutside({ pointerDownOutside: () => setIsOpened(false) }, [setIsOpened]);

    return (
        <Drawer.Root open={isOpened} onOpenChange={setIsOpened}>
            <Drawer.Content
                focusGuards={false}
                className="md:left-[var(--board-chat-sidebar-width,0px)] md:w-[calc(100%_-_var(--board-chat-sidebar-width,0px))]"
                overlayClassName="md:left-[var(--board-chat-sidebar-width,0px)]"
                onInteractOutside={onInteractOutside}
                onPointerDownOutside={onPointerDownOutside}
                {...{ [DISABLE_DRAGGING_ATTR]: "" }}
            >
                <Drawer.Title hidden />
                <Drawer.Description hidden />
                <BoardBotScopeList target={{ target_table: "project", target: project }} className="max-h-[50vh]" />
            </Drawer.Content>
        </Drawer.Root>
    );
}
BoardBotScopeDisplay.displayName = "Board.BotScopeDisplay";

export function BoardBotScopeList({ target, className }: IBoardBotScopeListProps) {
    const [t] = useTranslation();
    const socket = useSocket();
    const bots = BotModel.Model.useModels(() => true);
    const projectScopes = ProjectBotScope.Model.useModels(() => true);
    const columnScopes = ProjectColumnBotScope.Model.useModels(() => true);
    const cardScopes = ProjectCardBotScope.Model.useModels(() => true);
    const projectSchedules = ProjectBotSchedule.Model.useModels(() => true);
    const columnSchedules = ProjectColumnBotSchedule.Model.useModels(() => true);
    const cardSchedules = ProjectCardBotSchedule.Model.useModels(() => true);
    const defaultScopeBranches = BotDefaultScopeBranchModel.Model.useModels(() => true);
    const [searchOpened, setSearchOpened] = useState(false);
    const [search, setSearch] = useState("");
    const targetLabel = getBoardBotScopeTargetLabel(target);
    const projectUID = getBoardBotScopeTargetProjectUID(target);
    useGetGraphApprovals(
        {
            project_uid: projectUID,
            status: EGraphApprovalStatus.Pending,
            limit: 100,
        },
        {
            interceptToast: false,
        }
    );
    const graphApprovalRequestedHandlers = useBoardGraphApprovalRequestedHandlers({ projectUID });
    const graphApprovalUpdatedHandlers = useBoardGraphApprovalUpdatedHandlers({ projectUID });
    const graphApprovalDeletedHandlers = useBoardGraphApprovalDeletedHandlers({ projectUID });
    const graphApprovalHandlers = useMemo(
        () => [graphApprovalRequestedHandlers, graphApprovalUpdatedHandlers, graphApprovalDeletedHandlers],
        [graphApprovalRequestedHandlers, graphApprovalUpdatedHandlers, graphApprovalDeletedHandlers]
    );
    useSwitchSocketHandlers({ socket, handlers: graphApprovalHandlers, dependencies: [graphApprovalHandlers] });
    const pendingApprovals = GraphApprovalRequestModel.Model.useModels((approval) => {
        return (
            approval.project_uid === projectUID &&
            approval.status === EGraphApprovalStatus.Pending &&
            isBoardBotScopeGraphApprovalOriginType(approval.origin_type) &&
            approval.scope_table === target.target_table &&
            approval.scope_uid === target.target.uid
        );
    });
    const computedOnboardingByBotUID = useMemo(() => {
        const targetScopes = getTargetScopes(target.target_table, projectScopes, columnScopes, cardScopes);
        const nextOnboardingByBotUID: Record<string, bool> = {};

        targetScopes.forEach((scope) => {
            if (getScopeTargetUID(scope, target.target_table) !== target.target.uid) {
                return;
            }

            nextOnboardingByBotUID[scope.bot_uid] = getEffectiveBotScopeConditions(scope, target.target_table, defaultScopeBranches).length > 0;
        });

        return nextOnboardingByBotUID;
    }, [projectScopes, columnScopes, cardScopes, defaultScopeBranches, target]);
    const [onboardingByBotUID, setOnboardingByBotUID] = useState<Record<string, bool>>(computedOnboardingByBotUID);
    useEffect(() => {
        setOnboardingByBotUID(computedOnboardingByBotUID);
    }, [computedOnboardingByBotUID]);
    const updateOnboardingState = useCallback((botUID: string, isOnboarding: bool) => {
        setOnboardingByBotUID((prev) => {
            if (prev[botUID] === isOnboarding) {
                return prev;
            }

            return {
                ...prev,
                [botUID]: isOnboarding,
            };
        });
    }, []);
    const rows = useMemo(() => {
        const normalizedSearch = search.trim().toLowerCase();
        const targetScopes = getTargetScopes(target.target_table, projectScopes, columnScopes, cardScopes);
        const targetSchedules = getTargetSchedules(target.target_table, projectSchedules, columnSchedules, cardSchedules);
        const scopeMap = new Map<string, BaseBotScopeModel.TModel>();
        const scheduledBotUIDs = new Set<string>();
        targetScopes.forEach((scope) => {
            if (getScopeTargetUID(scope, target.target_table) === target.target.uid) {
                scopeMap.set(scope.bot_uid, scope);
            }
        });
        targetSchedules.forEach((schedule) => {
            if (getScheduleTargetUID(schedule, target.target_table) !== target.target.uid) {
                return;
            }
            if (schedule.status === BaseBotScheduleModel.EStatus.Stopped) {
                return;
            }

            scheduledBotUIDs.add(schedule.bot_uid);
        });

        const filteredRows = bots
            .map((bot): IBoardBotScopeRow => {
                const botScope = scopeMap.get(bot.uid);
                return {
                    botUID: bot.uid,
                    bot,
                    botScope,
                    hasScheduled: scheduledBotUIDs.has(bot.uid),
                };
            })
            .filter(({ bot }) => {
                if (!normalizedSearch) {
                    return true;
                }

                return bot.name.toLowerCase().includes(normalizedSearch) || bot.bot_uname.toLowerCase().includes(normalizedSearch);
            });

        return [...filteredRows.filter((row) => onboardingByBotUID[row.botUID]), ...filteredRows.filter((row) => !onboardingByBotUID[row.botUID])];
    }, [bots, projectScopes, columnScopes, cardScopes, projectSchedules, columnSchedules, cardSchedules, onboardingByBotUID, target, search]);

    return (
        <Box className="h-full min-h-0">
            <Flex direction="col" gap="2" className="h-full min-h-0">
                <Flex direction="col" gap="3" className="shrink-0 border-b px-3 py-3">
                    <Flex items="start" justify="between" gap="2">
                        <Box className="min-w-0 flex-1 rounded-lg border bg-muted/30 px-3 py-2">
                            <Flex items="center" gap="1.5" className="text-muted-foreground">
                                <IconComponent icon={getBoardBotScopeTargetIcon(target.target_table)} size="3.5" />
                                <Box textSize="xs">{t(`bot.target_tables.${target.target_table}`)}</Box>
                            </Flex>
                            <Box weight="semibold" textSize="sm" className="mt-0.5 break-words leading-snug">
                                {targetLabel}
                            </Box>
                        </Box>
                        <Flex items="center" gap="1">
                            <Button
                                type="button"
                                variant={searchOpened ? "secondary" : "ghost"}
                                size="icon-sm"
                                title={t("bot.Search bots")}
                                aria-label={t("bot.Search bots")}
                                onClick={() => setSearchOpened((value) => !value)}
                            >
                                <IconComponent icon="search" size="4" />
                            </Button>
                        </Flex>
                    </Flex>
                    {searchOpened && (
                        <Input
                            h="sm"
                            value={search}
                            placeholder={t("bot.Search bots...")}
                            clearable
                            onClear={() => setSearch("")}
                            onChange={(e) => setSearch(e.currentTarget.value)}
                        />
                    )}
                </Flex>
                <ScrollArea.Root className="min-h-0 flex-1 py-1">
                    <Flex direction="col" gap="2" px="2.5" className={className}>
                        <BoardGraphApprovalList approvals={pendingApprovals} projectUID={projectUID} />
                        {rows.map((row) => (
                            <BoardBotScopeItem key={row.botUID} row={row} target={target} onOnboardingChange={updateOnboardingState} />
                        ))}
                    </Flex>
                </ScrollArea.Root>
            </Flex>
        </Box>
    );
}

interface IBoardGraphApprovalListProps {
    approvals: GraphApprovalRequestModel.TModel[];
    projectUID: string;
}

function BoardGraphApprovalList({ approvals, projectUID }: IBoardGraphApprovalListProps): React.JSX.Element | null {
    const [t, i18n] = useTranslation();
    const runningApprovalUIDRef = useRef<string | null>(null);
    const [hiddenApprovalUIDs, setHiddenApprovalUIDs] = useState<Set<string>>(() => new Set());
    const approveMutation = useApproveGraphApproval({ interceptToast: true });
    const rejectMutation = useRejectGraphApproval({ interceptToast: true });
    const visibleApprovals = useMemo(() => {
        return approvals.filter((approval) => !hiddenApprovalUIDs.has(approval.uid));
    }, [approvals, hiddenApprovalUIDs]);

    if (!visibleApprovals.length) {
        return null;
    }

    const hideApproval = (approvalUID: string) => {
        setHiddenApprovalUIDs((prev) => new Set(prev).add(approvalUID));
    };

    const approve = (approval: GraphApprovalRequestModel.TModel) => {
        if (runningApprovalUIDRef.current) {
            return;
        }

        runningApprovalUIDRef.current = approval.uid;
        approveMutation
            .mutateAsync({ project_uid: projectUID, approval_uid: approval.uid })
            .then(() => hideApproval(approval.uid))
            .finally(() => {
                runningApprovalUIDRef.current = null;
            });
    };

    const reject = (approval: GraphApprovalRequestModel.TModel) => {
        if (runningApprovalUIDRef.current) {
            return;
        }

        runningApprovalUIDRef.current = approval.uid;
        rejectMutation
            .mutateAsync({ project_uid: projectUID, approval_uid: approval.uid })
            .then(() => hideApproval(approval.uid))
            .finally(() => {
                runningApprovalUIDRef.current = null;
            });
    };

    return (
        <Flex direction="col" gap="2" className="rounded-xl border border-primary/20 bg-primary/5 p-2">
            <Flex items="center" gap="1.5" className="text-primary">
                <IconComponent icon="hand" size="3.5" />
                <Box textSize="xs" weight="semibold">
                    {t("bot.Human input required")}
                </Box>
                <Badge variant="secondary" className="ml-auto px-2 py-0 text-[11px]">
                    {formatNumber(visibleApprovals.length, i18n.language)}
                </Badge>
            </Flex>
            {visibleApprovals.map((approval) => (
                <BoardGraphApprovalItem key={approval.uid} approval={approval} onApprove={approve} onReject={reject} onResolved={hideApproval} />
            ))}
        </Flex>
    );
}

interface IBoardGraphApprovalItemProps {
    approval: GraphApprovalRequestModel.TModel;
    onApprove: (approval: GraphApprovalRequestModel.TModel) => void;
    onReject: (approval: GraphApprovalRequestModel.TModel) => void;
    onResolved: (approvalUID: string) => void;
}

function BoardGraphApprovalItem({ approval, onApprove, onReject, onResolved }: IBoardGraphApprovalItemProps): React.JSX.Element | null {
    const [t] = useTranslation();
    const approvalUIDRef = useRef(approval.uid);
    const status = approval.useField("status");
    const originType = approval.useField("origin_type");
    const scopeTable = approval.useField("scope_table");
    const title = useGraphApprovalTitle(approval, t("bot.Approval request"));
    const summary = useGraphApprovalSummary(approval);

    useEffect(() => {
        if (status === EGraphApprovalStatus.Pending) {
            return;
        }

        onResolved(approvalUIDRef.current);
    }, [onResolved, status]);

    if (status !== EGraphApprovalStatus.Pending) {
        return null;
    }

    return (
        <Flex direction="col" gap="2" className="rounded-lg border bg-background/80 p-2">
            <Box className="min-w-0">
                <Flex items="center" gap="1.5" wrap={true} className="mb-1">
                    <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                        {t(`bot.approvalOriginTypes.${originType}`, { defaultValue: originType })}
                    </Badge>
                    <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                        {t(`bot.target_tables.${scopeTable}`, { defaultValue: scopeTable })}
                    </Badge>
                </Flex>
                <Box textSize="sm" weight="semibold" className="break-words leading-snug">
                    {title}
                </Box>
                {summary && (
                    <Box textSize="xs" className="mt-1 line-clamp-3 break-words text-muted-foreground">
                        {summary}
                    </Box>
                )}
            </Box>
            <Flex items="center" gap="1.5">
                <Button type="button" size="sm" className="h-7 flex-1 px-2" onClick={() => onApprove(approval)}>
                    {t("bot.Approve")}
                </Button>
                <Button type="button" variant="outline" size="sm" className="h-7 flex-1 px-2" onClick={() => onReject(approval)}>
                    {t("bot.Reject")}
                </Button>
            </Flex>
        </Flex>
    );
}

interface IBoardBotScopeItemProps {
    target: TBoardBotScopeTarget;
    row: IBoardBotScopeRow;
    onOnboardingChange: (botUID: string, isOnboarding: bool) => void;
}

const BoardBotScopeItem = memo(({ row, target, onOnboardingChange }: IBoardBotScopeItemProps) => {
    const hasBotScope = !!row.botScope;

    useEffect(() => {
        if (hasBotScope) {
            return;
        }

        onOnboardingChange(row.botUID, false);
    }, [hasBotScope, onOnboardingChange, row.botUID]);

    if (row.botScope) {
        return (
            <BoardBotScopeScopedItem
                row={row as IBoardBotScopeRow & { botScope: BaseBotScopeModel.TModel }}
                target={target}
                onOnboardingChange={onOnboardingChange}
            />
        );
    }

    return <BoardBotScopeItemContent row={row} target={target} isFrozen={false} isOnboarding={false} hasScheduled={row.hasScheduled} />;
});
BoardBotScopeItem.displayName = "Board.BotScopeItem";

function BoardBotScopeScopedItem({
    row,
    target,
    onOnboardingChange,
}: {
    target: TBoardBotScopeTarget;
    row: IBoardBotScopeRow & { botScope: BaseBotScopeModel.TModel };
    onOnboardingChange: (botUID: string, isOnboarding: bool) => void;
}): React.JSX.Element {
    const conditions = row.botScope.useField("conditions");
    const defaultScopeBranchUID = row.botScope.useField("default_scope_branch_uid");
    const isFrozen = row.botScope.useField("is_frozen");
    const defaultScopeBranch = defaultScopeBranchUID ? BotDefaultScopeBranchModel.Model.getModel(defaultScopeBranchUID) : null;
    const isOnboarding = !defaultScopeBranch && conditions.length > 0;

    useEffect(() => {
        if (defaultScopeBranch) {
            return;
        }

        onOnboardingChange(row.botUID, isOnboarding);
    }, [defaultScopeBranch, isOnboarding, onOnboardingChange, row.botUID]);

    if (defaultScopeBranch) {
        return (
            <BoardBotScopeDefaultBranchItem
                row={row}
                target={target}
                isFrozen={isFrozen}
                defaultScopeBranch={defaultScopeBranch}
                onOnboardingChange={onOnboardingChange}
            />
        );
    }

    return <BoardBotScopeItemContent row={row} target={target} isFrozen={isFrozen} isOnboarding={isOnboarding} hasScheduled={row.hasScheduled} />;
}

function BoardBotScopeDefaultBranchItem({
    row,
    target,
    isFrozen,
    defaultScopeBranch,
    onOnboardingChange,
}: {
    target: TBoardBotScopeTarget;
    row: IBoardBotScopeRow & { botScope: BaseBotScopeModel.TModel };
    isFrozen: bool;
    defaultScopeBranch: BotDefaultScopeBranchModel.TModel;
    onOnboardingChange: (botUID: string, isOnboarding: bool) => void;
}): React.JSX.Element {
    const branchConditionsMap = defaultScopeBranch.useField("conditions_map");
    const isOnboarding = (branchConditionsMap?.[target.target_table] || []).length > 0;

    useEffect(() => {
        onOnboardingChange(row.botUID, isOnboarding);
    }, [isOnboarding, onOnboardingChange, row.botUID]);

    return <BoardBotScopeItemContent row={row} target={target} isFrozen={isFrozen} isOnboarding={isOnboarding} hasScheduled={row.hasScheduled} />;
}

function BoardBotScopeItemContent({
    row,
    target,
    isFrozen,
    isOnboarding,
    hasScheduled,
}: Omit<IBoardBotScopeItemProps, "onOnboardingChange"> & { isFrozen: bool; isOnboarding: bool; hasScheduled: bool }): React.JSX.Element {
    const [t] = useTranslation();
    const { bot, botScope } = row;

    return (
        <Flex
            direction="col"
            gap="2"
            className={cn(
                "group rounded-xl border border-transparent px-2.5 py-2 transition-colors",
                "focus-within:border-border focus-within:bg-muted/50 hover:border-border hover:bg-muted/50",
                isFrozen && "bg-muted/25"
            )}
        >
            <Flex items="start" justify="between" gap="2">
                <Box className="min-w-0 flex-1">
                    <UserAvatar.Root
                        userOrBot={bot}
                        avatarSize="xs"
                        onlyAvatar
                        withNameProps={{
                            className: "inline-flex max-w-full gap-1 select-none",
                            nameClassName: "truncate text-sm font-semibold text-foreground",
                        }}
                    />
                    {(isOnboarding || hasScheduled) && (
                        <Flex items="center" gap="1.5" wrap={true} className="mt-1">
                            {isOnboarding && (
                                <Badge variant="secondary" className="px-2 py-0 text-[11px]">
                                    {t("bot.Onboarding")}
                                </Badge>
                            )}
                            {hasScheduled && (
                                <Badge variant="outline" className="px-2 py-0 text-[11px]">
                                    <IconComponent icon="clipboard-clock" size="3" className="mr-1" />
                                    {t("bot.Scheduled")}
                                </Badge>
                            )}
                        </Flex>
                    )}
                </Box>
                {isFrozen && (
                    <Badge variant="outline" className="shrink-0 px-2 py-0 text-[11px]">
                        <IconComponent icon="pause" size="3" className="mr-1" />
                        {t("bot.Frozen")}
                    </Badge>
                )}
            </Flex>

            <Flex
                items="center"
                gap="1"
                wrap={true}
                className={cn("flex opacity-0 transition-opacity", "group-focus-within:opacity-100", "group-hover:opacity-100")}
            >
                {isOnboarding && botScope && <BoardBotScopeFreezeButton bot={bot} botScope={botScope} target={target} />}
                <BoardBotScopeItemDialog title="bot.Triggers">
                    <BotTriggerConditionList
                        params={{
                            target_table: target.target_table,
                            target_uid: target.target.uid,
                            bot_uid: bot.uid,
                        }}
                        botUID={bot.uid}
                        botScope={botScope as TBotScopeModel<TBotScopeModelName> | undefined}
                    />
                </BoardBotScopeItemDialog>
                <BoardBotScopeItemDialog title="bot.Schedules">
                    <BotScheduleList
                        bot={bot}
                        params={{
                            target_table: target.target_table,
                            bot_uid: bot.uid,
                        }}
                        target={target.target}
                    />
                </BoardBotScopeItemDialog>
                <BoardBotScopeItemDialog title="bot.Logs">
                    <BotLogList
                        bot={bot}
                        params={{
                            target_table: target.target_table,
                        }}
                        target={target.target}
                    />
                </BoardBotScopeItemDialog>
            </Flex>
        </Flex>
    );
}

interface IBoardBotScopeFreezeButtonProps {
    target: TBoardBotScopeTarget;
    bot: BotModel.TModel;
    botScope: BaseBotScopeModel.TModel;
}

function BoardBotScopeFreezeButton({ target, bot, botScope }: IBoardBotScopeFreezeButtonProps): React.JSX.Element {
    const [t] = useTranslation();
    const isFrozen = botScope.useField("is_frozen");
    const isChangingRef = useRef(false);
    const { mutateAsync } = useToggleBotScopeFreeze(
        {
            target_table: target.target_table,
            target_uid: target.target.uid,
            bot_uid: bot.uid,
            bot_scope_uid: botScope.uid,
        },
        { interceptToast: true }
    );

    const toggleFreeze = () => {
        if (isChangingRef.current) {
            return;
        }

        isChangingRef.current = true;
        const promise = mutateAsync({ is_frozen: !isFrozen });
        promise.finally(() => {
            isChangingRef.current = false;
        });
        Toast.Add.promise(promise, {
            loading: t("common.Changing..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => t(isFrozen ? "successes.Bot unfrozen successfully." : "successes.Bot frozen successfully."),
        });
    };

    return (
        <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 gap-1 px-2"
            onPointerDown={(event) => {
                event.preventDefault();
                event.stopPropagation();
                toggleFreeze();
            }}
            onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
            }}
            onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") {
                    return;
                }

                event.preventDefault();
                event.stopPropagation();
                toggleFreeze();
            }}
        >
            <IconComponent icon={isFrozen ? "play" : "pause"} size="3.5" />
            {t(isFrozen ? "bot.Unfreeze" : "bot.Freeze")}
        </Button>
    );
}

function BoardBotScopeItemDialog({ title, children }: { title: string; children: React.ReactNode }) {
    const [t] = useTranslation();

    return (
        <Dialog.Root>
            <Dialog.Trigger asChild>
                <Button variant="ghost" size="sm" className="h-7 px-2">
                    {t(title)}
                </Button>
            </Dialog.Trigger>
            <Dialog.Content className="p-2 pt-8 sm:max-w-screen-sm md:max-w-screen-md lg:max-w-screen-lg" aria-describedby="">
                <Dialog.Title hidden />
                {children}
            </Dialog.Content>
        </Dialog.Root>
    );
}

function getTargetScopes(
    targetTable: TBotRelatedTargetTable,
    projectScopes: ProjectBotScope.TModel[],
    columnScopes: ProjectColumnBotScope.TModel[],
    cardScopes: ProjectCardBotScope.TModel[]
): BaseBotScopeModel.TModel[] {
    switch (targetTable) {
        case "project":
            return projectScopes;
        case "project_column":
            return columnScopes;
        case "card":
            return cardScopes;
    }
}

function getTargetSchedules(
    targetTable: TBotRelatedTargetTable,
    projectSchedules: ProjectBotSchedule.TModel[],
    columnSchedules: ProjectColumnBotSchedule.TModel[],
    cardSchedules: ProjectCardBotSchedule.TModel[]
): BaseBotScheduleModel.TModel[] {
    switch (targetTable) {
        case "project":
            return projectSchedules;
        case "project_column":
            return columnSchedules;
        case "card":
            return cardSchedules;
    }
}

function getScopeTargetUID(scope: BaseBotScopeModel.TModel, targetTable: TBotRelatedTargetTable): string {
    switch (targetTable) {
        case "project":
            return (scope as ProjectBotScope.TModel).project_uid;
        case "project_column":
            return (scope as ProjectColumnBotScope.TModel).project_column_uid;
        case "card":
            return (scope as ProjectCardBotScope.TModel).card_uid;
    }
}

function getScheduleTargetUID(schedule: BaseBotScheduleModel.TModel, targetTable: TBotRelatedTargetTable): string {
    switch (targetTable) {
        case "project":
            return (schedule as ProjectBotSchedule.TModel).project_uid;
        case "project_column":
            return (schedule as ProjectColumnBotSchedule.TModel).project_column_uid;
        case "card":
            return (schedule as ProjectCardBotSchedule.TModel).card_uid;
    }
}

function getEffectiveBotScopeConditions(
    botScope: BaseBotScopeModel.TModel | undefined,
    targetTable: TBotRelatedTargetTable,
    defaultScopeBranches: BotDefaultScopeBranchModel.TModel[]
): EBotTriggerCondition[] {
    if (!botScope) {
        return [];
    }

    if (!botScope.default_scope_branch_uid) {
        return botScope.conditions;
    }

    const defaultScopeBranch = defaultScopeBranches.find((branch) => branch.uid === botScope.default_scope_branch_uid);
    return defaultScopeBranch?.conditions_map?.[targetTable] || [];
}

function getBoardBotScopeTargetLabel(target: TBoardBotScopeTarget): string {
    switch (target.target_table) {
        case "project":
            return target.target.title;
        case "project_column":
            return target.target.name;
        case "card":
            return target.target.title;
    }
}

function getBoardBotScopeTargetProjectUID(target: TBoardBotScopeTarget): string {
    switch (target.target_table) {
        case "project":
            return target.target.uid;
        case "project_column":
        case "card":
            return target.target.project_uid;
    }
}

function getBoardBotScopeTargetIcon(targetTable: TBotRelatedTargetTable): string {
    switch (targetTable) {
        case "project":
            return "folder-kanban";
        case "project_column":
            return "columns-3";
        case "card":
            return "square-kanban";
    }
}

export default BoardBotScope;
