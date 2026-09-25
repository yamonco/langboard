import Button from "@/components/base/Button";
import Avatar from "@/components/base/Avatar";
import Card from "@/components/base/Card";
import Collapsible from "@/components/base/Collapsible";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import ShineBorder from "@/components/base/ShineBorder";
import { UserAvatarList } from "@/components/UserAvatarList";
import { DISABLE_DRAGGING_ATTR } from "@/constants";
import { useBoardController } from "@/core/providers/BoardController";
import { useBoard } from "@/core/providers/BoardProvider";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import SelectRelationshipDialog from "@/pages/BoardPage/components/board/SelectRelationshipDialog";
import BoardColumnCardRelationship from "@/pages/BoardPage/components/board/BoardColumnCardRelationship";
import { LabelModelBadge } from "@/components/LabelBadge";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { IBoardColumnCardContextParams } from "@/pages/BoardPage/components/board/BoardConstants";
import useCardStore, { useCardIsCollapsed } from "@/core/stores/CardStore";
import { useHasRunningBot } from "@/core/stores/BotStatusStore";
import BoardGraphApprovalTargetBadge from "@/pages/BoardPage/components/board/BoardGraphApprovalTargetBadge";
import { EGraphApprovalScopeTable } from "@/core/models/GraphApprovalRequestModel";
import { Utils } from "@langboard/core/utils";
import {
    calculateChecklistProgressFromCounts,
    calculateDeadlinePressure,
    getChecklistBorderDashes,
    getDeadlinePressureLevel,
    type IBoardCardChecklistProgress,
} from "@/pages/BoardPage/components/board/BoardColumnCardStatus";
import BoardTaskMetadataBadges from "@/pages/BoardPage/components/task/BoardTaskMetadataBadges";
import BoardCardMove from "@/pages/BoardPage/components/board/BoardCardMove";
import { getBoardCardWidgetVisibility } from "@/pages/BoardPage/components/board/BoardCardWidgetVisibility";
import useSetCardCompleted from "@/controllers/api/board/useSetCardCompleted";
import { captureCardOrigin } from "@/pages/BoardPage/components/board/CardAnimation";

export interface IBoardColumnCardCollapsibleProps {
    isDragging: bool;
    compact?: bool;
}

function BoardColumnCardCollapsible({ isDragging, compact = false }: IBoardColumnCardCollapsibleProps) {
    const { model: card } = ModelRegistry.ProjectCard.useContext<IBoardColumnCardContextParams>();

    if (card.source_type === "project_wiki") {
        return <BoardColumnWikiCard isDragging={isDragging} />;
    }

    return <BoardColumnTaskCard isDragging={isDragging} compact={compact} />;
}

function BoardColumnWikiCard({ isDragging }: IBoardColumnCardCollapsibleProps) {
    const { selectCardViewType } = useBoardController();
    const { project, navigateWithFilters } = useBoard();
    const [t] = useTranslation();
    const { model: card } = ModelRegistry.ProjectCard.useContext<IBoardColumnCardContextParams>();
    const resource = card.useField("linked_resource");
    const openCard = useCallback(
        (event: React.MouseEvent<HTMLDivElement>) => {
            if (selectCardViewType || isDragging) {
                return;
            }

            captureCardOrigin(project.uid, card.uid, event.currentTarget.getBoundingClientRect());
            navigateWithFilters(ROUTES.BOARD.CARD(project.uid, card.uid));
        },
        [card.uid, isDragging, navigateWithFilters, project.uid, selectCardViewType]
    );

    if (!resource) {
        return null;
    }

    const isAvailable = resource.status === "available";
    const resourceTitle = isAvailable ? resource.title : undefined;
    const fallbackTitle = resource.status === "forbidden" ? t("wiki.Restricted wiki") : t("wiki.Source unavailable");

    return (
        <Card.Root
            id={`board-card-${card.uid}`}
            className={cn(
                "group relative cursor-pointer overflow-hidden border-amber-400/35 bg-gradient-to-br from-amber-50/85 to-background",
                "shadow-sm transition hover:border-amber-500/65 hover:shadow-md dark:from-amber-950/20 dark:to-card",
                !!selectCardViewType && "cursor-not-allowed opacity-50"
            )}
            onClick={openCard}
        >
            <Card.Header className="space-y-2 px-5 py-4">
                <Flex items="center" justify="between" gap="2">
                    <Flex items="center" gap="2" className="min-w-0 text-amber-700 dark:text-amber-300">
                        <IconComponent icon={isAvailable ? "book-text" : "lock"} size="4" />
                        <span className="text-xs font-semibold uppercase tracking-[0.12em]">{t("wiki.Linked wiki")}</span>
                    </Flex>
                    <IconComponent icon="external-link" size="3.5" className="shrink-0 text-muted-foreground opacity-60" />
                </Flex>
                <Card.Title className="break-words text-[0.95rem] leading-snug">{resourceTitle || fallbackTitle}</Card.Title>
            </Card.Header>
        </Card.Root>
    );
}

function BoardColumnTaskCard({ isDragging, compact = false }: IBoardColumnCardCollapsibleProps) {
    const { selectCardViewType, selectedRelationshipUIDs, currentCardUIDRef, isDisabledCard } = useBoardController();
    const { project, filters, cardsMap, globalRelationshipTypes, navigateWithFilters, deadlineClock } = useBoard();
    const [t] = useTranslation();
    const { model: card } = ModelRegistry.ProjectCard.useContext<IBoardColumnCardContextParams>();
    const title = card.useField("title");
    const deadlineAt = card.useField("deadline_at");
    const checklistCompletedCount = card.useField("checklist_completed_count") ?? 0;
    const checklistTotalCount = card.useField("checklist_total_count") ?? 0;
    const checklistProgress = useMemo(
        () => calculateChecklistProgressFromCounts(checklistCompletedCount, checklistTotalCount),
        [checklistCompletedCount, checklistTotalCount]
    );
    const isChecklistCompleted = checklistProgress.total > 0 && checklistProgress.completed === checklistProgress.total;
    const deadlinePressure = useMemo(
        () => calculateDeadlinePressure({ deadlineAt, isCompleted: isChecklistCompleted, now: deadlineClock }),
        [deadlineAt, isChecklistCompleted, deadlineClock]
    );
    const deadlinePressureLevel = useMemo(
        () => getDeadlinePressureLevel({ deadlineAt, isCompleted: isChecklistCompleted, now: deadlineClock }),
        [deadlineAt, isChecklistCompleted, deadlineClock]
    );
    const projectMembers = project.useForeignFieldArray("all_members");
    const cardMemberUIDs = card.useField("member_uids") ?? [];
    const cardMembers = useMemo(
        () => projectMembers.filter((member) => member.isValidUser() && cardMemberUIDs.includes(member.uid)),
        [projectMembers, cardMemberUIDs]
    );
    const commentCount = card.useField("count_comment");
    const creator = card.useField("creator");
    const hasDescription = card.useField("has_description");
    const isCheckCard = card.useField("is_check_card") ?? false;
    const completed = card.useField("completed") ?? false;
    const widgetVisibility = useMemo(
        () => getBoardCardWidgetVisibility({ has_description: hasDescription, count_comment: commentCount }),
        [hasDescription, commentCount]
    );
    const { mutateAsync: setCardCompletedAsync } = useSetCardCompleted({ interceptToast: true });
    const hasUnreadChange = card.useField("has_unread_change") ?? false;
    const { updateCollapsed } = useCardStore();
    const isCollapsed = useCardIsCollapsed(card.uid);
    const labels = card.useForeignFieldArray("labels");
    const cardRelationships = card.useForeignFieldArray("relationships");
    const hasRunningBot = useHasRunningBot({ type: "card", targetUID: card.uid });
    const [isSelectRelationshipDialogOpened, setIsSelectRelationshipDialogOpened] = useState(false);
    const selectedRelationship = useMemo(
        () => (selectCardViewType ? selectedRelationshipUIDs.find(([selectedCardUID]) => selectedCardUID === card.uid)?.[1] : undefined),
        [card, selectCardViewType, selectedRelationshipUIDs]
    );
    const openCard = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if ((e.target as HTMLElement)?.closest?.(`[${DISABLE_DRAGGING_ATTR}]`)) {
                return;
            }

            if (selectCardViewType) {
                if (isDisabledCard(card.uid)) {
                    return;
                }

                setIsSelectRelationshipDialogOpened(true);
                return;
            }

            if (isDragging) {
                return;
            }

            captureCardOrigin(project.uid, card.uid, e.currentTarget.getBoundingClientRect());
            navigateWithFilters(ROUTES.BOARD.CARD(project.uid, card.uid));
        },
        [card, isDragging, isDisabledCard, navigateWithFilters, project, selectCardViewType]
    );

    const handleToggleCompleted = useCallback(
        (e: React.MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            e.stopPropagation();
            const nextCompleted = !completed;
            // Optimistic toggle; the hidden completion checklist persists the real state.
            card.update({ completed: nextCompleted });
            setCardCompletedAsync({ project_uid: project.uid, card_uid: card.uid, completed: nextCompleted }).catch(() => {
                card.update({ completed });
            });
        },
        [card, completed, project.uid, setCardCompletedAsync]
    );

    const handleOpenCollapsible = useCallback(
        (e: React.MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            e.stopPropagation();
            updateCollapsed(card.uid, !isCollapsed);
        },
        [card, isCollapsed, updateCollapsed]
    );
    const presentableRelationships = useMemo(() => {
        const relationships: [string, string][] = [];

        const filteredRelationships = cardRelationships.filter((relationship) => {
            if (!globalRelationshipTypes.length) {
                return false;
            }

            if (filters.parents) {
                return filters.parents.includes(relationship.child_card_uid);
            } else if (filters.children) {
                return filters.children.includes(relationship.parent_card_uid);
            } else {
                return false;
            }
        });

        const selectedRelationshipType = selectedRelationship
            ? globalRelationshipTypes.find((relationship) => relationship.uid === selectedRelationship)
            : undefined;

        for (let i = 0; i < filteredRelationships.length; ++i) {
            const relationship = filteredRelationships[i];
            const relationshipType = relationship.relationship_type;
            if (relationshipType) {
                const isParent = relationship.parent_card_uid === card.uid;
                const oppositeCard = cardsMap[isParent ? relationship.child_card_uid : relationship.parent_card_uid];
                if (!oppositeCard) {
                    continue;
                }
                relationships.push([oppositeCard.title, isParent ? relationshipType.child_name : relationshipType.parent_name]);
            }
        }

        if (selectedRelationshipType && currentCardUIDRef.current && cardsMap[currentCardUIDRef.current]) {
            const isParent = selectCardViewType === "parents";
            relationships.push([
                cardsMap[currentCardUIDRef.current].title,
                isParent ? selectedRelationshipType.parent_name : selectedRelationshipType.child_name,
            ]);
        }

        return relationships;
    }, [card, cardsMap, cardRelationships, filters, globalRelationshipTypes, selectCardViewType, selectedRelationship]);

    useEffect(() => {
        if (selectCardViewType && selectedRelationship) {
            updateCollapsed(card.uid, false);
        }
    }, [card, selectCardViewType, selectedRelationship, updateCollapsed]);

    useEffect(() => {
        if (presentableRelationships.length) {
            updateCollapsed(card.uid, false);
        }
    }, [card, filters, presentableRelationships.length, updateCollapsed]);

    const attributes = {
        [DISABLE_DRAGGING_ATTR]: "",
    };

    // Check cards stay collapsed: no expand affordances, no always-on meta, only a hover checkbox.
    const showCollapsedOnly = isCheckCard && !compact;

    return (
        <>
            <Card.Root
                id={`board-card-${card.uid}`}
                data-deadline-pressure-level={deadlinePressureLevel}
                className={cn(
                    "group/card relative hover:border-primary",
                    compact && "border-border/60 bg-background/80 shadow-none transition-colors hover:bg-background",
                    checklistProgress.total > 0 && "border-transparent hover:border-transparent",
                    !!selectCardViewType && isDisabledCard(card.uid) ? "cursor-not-allowed" : "cursor-pointer"
                )}
                style={{ "--board-card-deadline-pressure": deadlinePressure } as React.CSSProperties}
                onClick={openCard}
            >
                <BoardCardProgressTrace progress={checklistProgress} />
                {checklistProgress.total > 0 && (
                    <span className="sr-only">
                        {[
                            t("card.Checklist progress: {{completed}} of {{total}} complete", {
                                completed: checklistProgress.completed,
                                total: checklistProgress.total,
                            }),
                            deadlineAt && t("card.Deadline {{date}}", { date: Utils.String.formatDateLocale(deadlineAt) }),
                            deadlinePressureLevel === "critical" && t("card.Due within a day"),
                            deadlinePressureLevel === "overdue" && t("card.Overdue"),
                        ]
                            .filter(Boolean)
                            .join(" ")}
                    </span>
                )}
                {hasRunningBot && <ShineBorder className="z-50" />}
                {hasUnreadChange && (
                    <span
                        aria-label={t("board.Unread changes")}
                        title={t("board.Unread changes")}
                        className="absolute right-1.5 top-1.5 z-40 size-2 rounded-full bg-primary"
                    />
                )}
                <Collapsible.Root
                    open={!compact && !isCollapsed && !showCollapsedOnly}
                    onOpenChange={(opened) => {
                        updateCollapsed(card.uid, !opened);
                    }}
                >
                    <Card.Header className={cn("relative block space-y-0", compact ? "px-3 py-2" : "py-4", showCollapsedOnly && "py-2.5")}>
                        {!compact && !isCollapsed && !showCollapsedOnly && !!labels.length && (
                            <Flex items="center" gap="1" mb="1.5" wrap>
                                {labels.map((label) => (
                                    <LabelModelBadge key={`board-card-label-${label.uid}`} model={label} />
                                ))}
                            </Flex>
                        )}
                        {!compact && !isCollapsed && !showCollapsedOnly && <BoardTaskMetadataBadges cardUID={card.uid} compact className="mb-1.5" />}
                        <Card.Title
                            className={cn(
                                "break-all leading-tight",
                                compact ? "max-w-full text-sm font-medium text-muted-foreground" : "max-w-[calc(100%_-_theme(spacing.8))]",
                                showCollapsedOnly && "text-sm",
                                completed && "line-through opacity-60"
                            )}
                        >
                            <button
                                type="button"
                                data-board-card-open=""
                                className={cn(
                                    "w-full rounded-sm text-left [font:inherit]",
                                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                )}
                                disabled={!!selectCardViewType && isDisabledCard(card.uid)}
                            >
                                {title}
                            </button>
                        </Card.Title>
                        {showCollapsedOnly && (
                            <Button
                                variant="ghost"
                                className="absolute left-1.5 top-1/2 z-10 -translate-y-1/2 opacity-0 transition-opacity group-hover/card:opacity-100"
                                size="icon-sm"
                                title={t(completed ? "card.Mark as not done" : "card.Mark as done")}
                                titleSide="top"
                                onClick={handleToggleCompleted}
                                {...attributes}
                            >
                                <IconComponent icon={completed ? "check" : "circle"} size="4" className="text-muted-foreground" />
                            </Button>
                        )}
                        {!compact && !showCollapsedOnly && (
                            <BoardGraphApprovalTargetBadge
                                projectUID={project.uid}
                                scopeTable={EGraphApprovalScopeTable.Card}
                                scopeUID={card.uid}
                                className="absolute right-11 top-3"
                            />
                        )}
                        {!compact && !showCollapsedOnly && (
                            <Button
                                variant="ghost"
                                className={cn("absolute right-0 top-0 mt-0 size-11 md:right-1 md:top-1 md:size-8")}
                                size="icon-sm"
                                title={t(`common.${!isCollapsed ? "Collapse" : "Expand"}`)}
                                titleSide="top"
                                onClick={handleOpenCollapsible}
                                {...attributes}
                            >
                                <IconComponent icon="chevron-down" size="4" className={cn("transition-all", !isCollapsed && "rotate-180")} />
                            </Button>
                        )}
                    </Card.Header>
                    {showCollapsedOnly ? (
                        <>
                            {!!cardMembers.length && (
                                <div className="flex items-center justify-end px-4 pb-1.5">
                                    <UserAvatarList
                                        maxVisible={3}
                                        userOrBots={cardMembers}
                                        scope={{
                                            projectUID: project.uid,
                                            cardUID: card.uid,
                                        }}
                                        size="sm"
                                        {...attributes}
                                        className="cursor-default"
                                    />
                                </div>
                            )}
                            <div className="flex items-center px-4 pb-2 opacity-0 transition-opacity duration-200 group-hover/card:opacity-100">
                                {creator && (
                                    <span
                                        title={t("card.Created by {{name}}", {
                                            name: creator.name,
                                        })}
                                        className={cn(
                                            "mr-0 inline-flex max-w-0 overflow-hidden opacity-0 transition-all duration-200 ease-out",
                                            "group-hover/card:mr-2 group-hover/card:max-w-8 group-hover/card:opacity-100"
                                        )}
                                        {...attributes}
                                    >
                                        <Avatar.Root size="xs">
                                            {creator.avatar && (
                                                <Avatar.Image src={Utils.String.convertServerFileURL(creator.avatar)} alt={creator.name} />
                                            )}
                                            <Avatar.Fallback className="text-[10px] font-medium">
                                                {Utils.String.getInitials(creator.name, "")}
                                            </Avatar.Fallback>
                                        </Avatar.Root>
                                    </span>
                                )}
                                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                    {commentCount ? (
                                        <>
                                            <IconComponent icon="message-square" size="3.5" />
                                            <span>{commentCount}</span>
                                        </>
                                    ) : null}
                                </span>
                            </div>
                        </>
                    ) : (
                        <Collapsible.Content
                            className={cn(
                                "overflow-hidden text-sm transition-all",
                                "data-[state=closed]:animate-collapse-up data-[state=open]:animate-collapse-down"
                            )}
                        >
                            {!!presentableRelationships.length && (
                                <Card.Content className="px-6 pb-4">
                                    {presentableRelationships.map(([relatedCardTitle, relationshipName], index) => (
                                        <Flex
                                            key={`board-card-presentable-relationship-${card.uid}-${relationshipName}-${relatedCardTitle}-${index}`}
                                            items="center"
                                            gap="2"
                                            className="truncate text-accent-foreground/70"
                                        >
                                            <span>{relationshipName}</span>
                                            <span className="text-muted-foreground">&gt;</span>
                                            <span className="truncate">{relatedCardTitle}</span>
                                        </Flex>
                                    ))}
                                </Card.Content>
                            )}
                            <Card.Footer className="flex items-end justify-between gap-1.5 pb-4">
                                <Flex items="center">
                                    {creator && (
                                        <span
                                            title={t("card.Created by {{name}}", {
                                                name: creator.name,
                                            })}
                                            className={cn(
                                                "mr-0 inline-flex max-w-0 overflow-hidden opacity-0 transition-all duration-200 ease-out",
                                                "group-hover/card:mr-2 group-hover/card:max-w-8 group-hover/card:opacity-100"
                                            )}
                                            {...attributes}
                                        >
                                            <Avatar.Root size="xs">
                                                {creator.avatar && (
                                                    <Avatar.Image src={Utils.String.convertServerFileURL(creator.avatar)} alt={creator.name} />
                                                )}
                                                <Avatar.Fallback className="text-[10px] font-medium">
                                                    {Utils.String.getInitials(creator.name, "")}
                                                </Avatar.Fallback>
                                            </Avatar.Root>
                                        </span>
                                    )}
                                    {widgetVisibility.showDescriptionIcon && (
                                        <IconComponent
                                            icon="file-text"
                                            size="4"
                                            className="text-secondary"
                                            strokeWidth="4"
                                            {...attributes}
                                            aria-label={t("card.Description")}
                                        />
                                    )}
                                    {widgetVisibility.showCommentCount && (
                                        <span className="ml-2 flex items-center gap-1">
                                            <IconComponent icon="message-square" size="4" className="text-secondary" strokeWidth="4" />
                                            <span>{commentCount}</span>
                                        </span>
                                    )}
                                </Flex>
                                <UserAvatarList
                                    maxVisible={3}
                                    userOrBots={cardMembers}
                                    scope={{
                                        projectUID: project.uid,
                                        cardUID: card.uid,
                                    }}
                                    size="sm"
                                    {...attributes}
                                    className="cursor-default"
                                />
                            </Card.Footer>
                        </Collapsible.Content>
                    )}
                </Collapsible.Root>
                <BoardColumnCardRelationship attributes={attributes} compact={compact} />
            </Card.Root>
            <SelectRelationshipDialog isOpened={isSelectRelationshipDialogOpened} setIsOpened={setIsSelectRelationshipDialogOpened} />
        </>
    );
}

function BoardCardProgressTrace({ progress }: { progress: IBoardCardChecklistProgress }) {
    const frameRef = useRef<HTMLSpanElement>(null);
    const [size, setSize] = useState({ width: 0, height: 0, radius: 0 });
    const hasChecklist = progress.total > 0;

    useLayoutEffect(() => {
        const frame = frameRef.current;
        if (!frame) return;

        const measure = () => {
            const next = {
                width: frame.clientWidth,
                height: frame.clientHeight,
                radius: parseFloat(getComputedStyle(frame).borderTopLeftRadius) || 0,
            };
            setSize((current) => (current.width === next.width && current.height === next.height && current.radius === next.radius ? current : next));
        };
        measure();
        const observer = new ResizeObserver(measure);
        observer.observe(frame);
        return () => observer.disconnect();
    }, [hasChecklist]);

    if (!hasChecklist) {
        return null;
    }

    const strokeWidth = 2.5;
    const inset = strokeWidth / 2;
    const width = Math.max(0, size.width - strokeWidth);
    const height = Math.max(0, size.height - strokeWidth);
    const radius = Math.max(0, size.radius - inset);
    const perimeter = 2 * (width + height - 4 * radius) + 2 * Math.PI * radius;
    const completed = Math.min(progress.total, Math.max(0, progress.completed));
    const dashes = getChecklistBorderDashes(completed, progress.total, perimeter);

    return (
        <span ref={frameRef} aria-hidden="true" className="pointer-events-none absolute inset-0 z-[1] overflow-hidden rounded-[inherit]">
            {size.width > strokeWidth && size.height > strokeWidth && (
                <svg className="h-full w-full" viewBox={`0 0 ${size.width} ${size.height}`}>
                    <rect
                        className="board-card-progress-track"
                        x={inset}
                        y={inset}
                        width={width}
                        height={height}
                        rx={radius}
                        ry={radius}
                        pathLength={progress.total}
                        style={{ strokeDasharray: dashes.track }}
                    />
                    {completed > 0 && (
                        <rect
                            className="board-card-progress-value"
                            x={inset}
                            y={inset}
                            width={width}
                            height={height}
                            rx={radius}
                            ry={radius}
                            pathLength={progress.total}
                            style={{ strokeDasharray: dashes.value }}
                        />
                    )}
                </svg>
            )}
        </span>
    );
}
BoardColumnCardCollapsible.displayName = "Board.ColumnCard.Collapsible";

export default BoardColumnCardCollapsible;
