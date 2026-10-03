import { formatNumber } from "@/core/utils/LocaleFormat";
import { metadataDisplay } from "@/core/utils/MetadataDisplay";
import useProjectWorkflowStages from "@/controllers/api/board/useProjectWorkflowStages";
import Button from "@/components/base/Button";
import Checkbox from "@/components/base/Checkbox";
import Avatar from "@/components/base/Avatar";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Input from "@/components/base/Input";
import Label from "@/components/base/Label";
import Popover from "@/components/base/Popover";
import Skeleton from "@/components/base/Skeleton";
import UserAvatar from "@/components/UserAvatar";
import { IFilterMap, useBoard } from "@/core/providers/BoardProvider";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import BoardLabelListItem from "@/pages/BoardPage/components/board/BoardLabelListItem";
import { CheckedState } from "@radix-ui/react-checkbox";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

export function SkeletonBoardFilter() {
    return <Skeleton h="9" w={{ initial: "7", xs: "14" }} px={{ xs: "4" }} />;
}

function BoardFilter() {
    const { project, columns, cards, currentUser, filters, filterCard, filterMember, filterLabel, navigateWithFilters } = useBoard();
    const [t, i18n] = useTranslation();
    const [open, setOpen] = useState(false);
    const stages = useProjectWorkflowStages(project.uid, open || Boolean(filters.workflow_stages?.length));
    const stageName = (key: string) => {
        const stage = stages.data?.find((item) => item.key === key);
        return stage ? metadataDisplay(stage, stage.translations, i18n.resolvedLanguage ?? i18n.language).name : key;
    };
    const [category, setCategory] = useState<"status" | "workflow" | "members" | "creators" | "labels" | "relationships" | null>(null);
    const categories = [
        { key: "status", label: t("board.filters.Status"), keys: ["unfinished", "columns"] },
        { key: "workflow", label: t("common.Workflow stage"), keys: ["workflow_stages"] },
        { key: "members", label: t("board.filters.Assignee"), keys: ["members"] },
        { key: "creators", label: t("board.filters.Creator"), keys: ["creators"] },
        { key: "labels", label: t("board.filters.Labels"), keys: ["labels"] },
        { key: "relationships", label: t("board.filters.Relationships"), keys: ["parents", "children"] },
    ] as const;
    const labels = project.useForeignFieldArray("labels");
    const creators = useMemo(() => {
        const choices = new Map<string, string>();
        for (const member of project.all_members) {
            if (member.isValidUser() && !project.invited_member_uids.includes(member.uid)) {
                choices.set(`user/${member.uid}`, `${member.firstname} ${member.lastname}`.trim() || member.username);
            }
        }
        // Historical creators may no longer be members; use only this authorized board's compact card projection.
        for (const card of cards) {
            if (card.creator) choices.set(`${card.creator.type}/${card.creator.uid}`, card.creator.name);
        }
        choices.delete(`user/${currentUser.uid}`);
        return [...choices];
    }, [cards, project.all_members, currentUser.uid]);

    const setFilterKeyword = (event: React.ChangeEvent<HTMLInputElement>) => {
        if (!filters.keyword) {
            filters.keyword = [];
        }

        const keyword = event.currentTarget.value;

        if (filters.keyword.includes(keyword)) {
            return;
        }

        if (keyword) filters.keyword = keyword.split(",");
        else delete filters.keyword;

        navigateWithFilters(ROUTES.BOARD.MAIN(project.uid));
    };

    const countAppliedFilters =
        Number((filters.keyword?.length ?? 0) > 0) +
        Object.keys(filters)
            .filter((v) => v !== "keyword")
            .reduce((acc: number, filterName) => acc + filters[filterName as keyof IFilterMap]!.length, 0);

    const clearFilters = (event: React.MouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        Object.keys(filters).forEach((filterName) => {
            delete filters[filterName as keyof IFilterMap];
        });
        navigateWithFilters(ROUTES.BOARD.MAIN(project.uid));
    };

    const filteredLabels = labels.filter((label) => filterLabel(label));

    const removeFilter = (name: keyof IFilterMap, value: string) => {
        filters[name] = filters[name]?.filter((item) => item !== value);
        if (!filters[name]?.length) delete filters[name];
        navigateWithFilters(ROUTES.BOARD.MAIN(project.uid));
    };

    const filterTitle = (name: keyof IFilterMap, value: string) => {
        if (name === "keyword") return `${t("board.filters.Keyword")}: ${value}`;
        if (name === "workflow_stages") return `${t("common.Workflow stage")}: ${stageName(value)}`;
        if (name === "unfinished") return t("dashboard.Unfinished cards");
        if (name === "columns") return `${t("board.filters.Status")}: ${columns.find((item) => item.uid === value)?.name ?? t("common.Unknown")}`;
        if (name === "members") {
            const member = project.all_members.find((item) => item.email === value);
            const label =
                value === "none"
                    ? t("board.filters.No members assigned")
                    : value === "me"
                      ? t("board.filters.Assigned to me")
                      : member
                        ? `${member.firstname} ${member.lastname}`.trim() || member.username
                        : t("common.Unknown");
            return `${t("board.filters.Assignee")}: ${label}`;
        }

        if (name === "creators")
            // eslint-disable-next-line @/max-len
            return `${t("board.filters.Creator")}: ${value === "me" ? t("board.filters.Created by me") : (creators.find(([key]) => key === value)?.[1] ?? t("common.Unknown"))}`;
        if (name === "labels") return `${t("board.filters.Labels")}: ${labels.find((item) => item.uid === value)?.name ?? t("common.Unknown")}`;
        return `${t(`board.filters.relationships.${name}`)}: ${cards.find((item) => item.uid === value)?.title ?? t("common.Unknown")}`;
    };

    return (
        <div className="flex min-w-0 flex-wrap items-center gap-1">
            <Popover.Root
                onOpenChange={(open) => {
                    setOpen(open);
                    if (open) setCategory(null);
                }}
            >
                <Popover.Trigger asChild>
                    <Button variant="ghost" aria-label={t("board.Filters")} className="gap-1 px-2 text-xs xs:px-4 xs:text-sm">
                        <IconComponent icon="list-filter" size={{ initial: "3", xs: "4" }} />
                        <span>{t("board.Filters")}</span>
                        {countAppliedFilters > 0 && <span>{` (${formatNumber(countAppliedFilters, i18n.language)})`}</span>}
                    </Button>
                </Popover.Trigger>
                <Popover.Content align="end" className="w-[34rem] max-w-[calc(100vw-2rem)] p-0">
                    <div className="space-y-2 border-b p-3">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-sm font-medium">{t("board.Filters")}</span>
                            <Button variant="ghost" size="sm" disabled={!countAppliedFilters} onClick={clearFilters}>
                                {t("board.filters.Clear")}
                            </Button>
                        </div>
                        <Input
                            aria-label={t("board.filters.Keyword")}
                            placeholder={t("board.filters.Keyword")}
                            value={filters.keyword?.join(",") ?? ""}
                            onChange={setFilterKeyword}
                        />
                    </div>
                    <div className="flex h-[min(24rem,60vh)] min-h-0">
                        <nav
                            aria-label={t("board.filters.Categories")}
                            className={cn("w-full shrink-0 space-y-1 overflow-y-auto p-2 sm:w-40 sm:border-r", category && "hidden sm:block")}
                        >
                            {categories.map((item) => {
                                const count = item.keys.reduce((sum, key) => sum + (filters[key]?.length ?? 0), 0);
                                return (
                                    <Button
                                        key={item.key}
                                        variant="ghost"
                                        aria-label={item.label}
                                        aria-pressed={category === item.key}
                                        className="w-full justify-between gap-2 px-2 text-sm aria-pressed:bg-accent"
                                        onClick={() => setCategory(item.key)}
                                    >
                                        <span>{item.label}</span>
                                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                            {count > 0 && formatNumber(count, i18n.language)}
                                            <IconComponent icon="chevron-right" size="3" />
                                        </span>
                                    </Button>
                                );
                            })}
                        </nav>
                        <div
                            className={cn("min-w-0 flex-1 overflow-y-auto p-2", !category && "hidden sm:block")}
                            aria-label={category ? categories.find((item) => item.key === category)?.label : t("board.filters.Select a category")}
                        >
                            {category ? (
                                <Button variant="ghost" size="sm" className="mb-2 gap-1 sm:hidden" onClick={() => setCategory(null)}>
                                    <IconComponent icon="arrow-left" size="4" />
                                    {t("board.filters.Back to categories")}
                                </Button>
                            ) : (
                                <p className="p-3 text-sm text-muted-foreground">{t("board.filters.Select a category")}</p>
                            )}
                            {category === "status" && (
                                <Flex direction="col">
                                    <Label>{t("dashboard.Unfinished by status")}</Label>
                                    <BoardFilterItem name="unfinished" value="yes">
                                        {t("dashboard.Unfinished cards")}
                                    </BoardFilterItem>
                                    {columns
                                        .filter((column) => !column.is_archive)
                                        .map((column) => (
                                            <BoardFilterItem key={column.uid} name="columns" value={column.uid}>
                                                {column.name}
                                            </BoardFilterItem>
                                        ))}
                                </Flex>
                            )}
                            {category === "workflow" && (
                                <Flex direction="col">
                                    <Label>{t("common.Workflow stage")}</Label>
                                    {stages.isPending && <Skeleton h="8" />}
                                    {stages.isError && (
                                        <Button variant="ghost" onClick={() => stages.refetch()}>
                                            {t("common.Retry")}
                                        </Button>
                                    )}
                                    {stages.data
                                        ?.filter((stage) => stage.is_active || filters.workflow_stages?.includes(stage.key))
                                        .map((stage) => (
                                            <BoardFilterItem key={stage.key} name="workflow_stages" value={stage.key}>
                                                <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: stage.color }} />
                                                {stageName(stage.key)}
                                            </BoardFilterItem>
                                        ))}
                                </Flex>
                            )}
                            {category === "members" && (
                                <Flex direction="col">
                                    <Label>{t("board.filters.Assignee")}</Label>
                                    <Flex direction="col" pt="1">
                                        <BoardFilterItem name="members" value="none">
                                            <span>{t("board.filters.No members assigned")}</span>
                                        </BoardFilterItem>
                                        <BoardFilterItem name="members" value="me">
                                            <UserAvatar.Root userOrBot={currentUser} withNameProps={{ className: "gap-1" }} avatarSize="xs" />
                                            <span className="sr-only">{t("board.filters.Assigned to me")}</span>
                                        </BoardFilterItem>
                                        <BoardExtendedFilter
                                            filterLangLabel="Select members"
                                            uncountableItems={["none", "me"]}
                                            filterName="members"
                                            createFilterItems={() =>
                                                project.all_members
                                                    .filter(
                                                        (member) =>
                                                            member.isValidUser() &&
                                                            !project.invited_member_uids.includes(member.uid) &&
                                                            filterMember(member)
                                                    )
                                                    .map((member) => (
                                                        <BoardFilterItem
                                                            key={`board-filter-member-${member.uid}`}
                                                            name="members"
                                                            value={member.email}
                                                        >
                                                            <UserAvatar.Root
                                                                userOrBot={member}
                                                                withNameProps={{ className: "gap-1" }}
                                                                avatarSize="xs"
                                                            />
                                                        </BoardFilterItem>
                                                    ))
                                            }
                                        />
                                    </Flex>
                                </Flex>
                            )}
                            {category === "creators" && (
                                <Flex direction="col">
                                    <Label>{t("board.filters.Creator")}</Label>
                                    <BoardFilterItem name="creators" value="me">
                                        <UserAvatar.Root userOrBot={currentUser} withNameProps={{ className: "gap-1" }} avatarSize="xs" />
                                        <span className="sr-only">{t("board.filters.Created by me")}</span>
                                    </BoardFilterItem>
                                    <BoardExtendedFilter
                                        filterLangLabel="Select creators"
                                        uncountableItems={["me"]}
                                        filterName="creators"
                                        createFilterItems={() =>
                                            creators.map(([key, name]) => (
                                                <BoardFilterItem key={key} name="creators" value={key}>
                                                    <CreatorChoice creatorKey={key} name={name} />
                                                </BoardFilterItem>
                                            ))
                                        }
                                    />
                                </Flex>
                            )}
                            {category === "labels" && (
                                <Flex direction="col">
                                    <Label>{t("board.filters.Labels")}</Label>
                                    <Flex direction="col" pt="1">
                                        {filteredLabels.slice(0, 2).map((label) => (
                                            <BoardFilterItem key={`board-filter-label-${label.uid}`} name="labels" value={label.uid}>
                                                <BoardLabelListItem label={label} />
                                            </BoardFilterItem>
                                        ))}
                                        {filteredLabels.length > 2 && (
                                            <BoardExtendedFilter
                                                filterLangLabel="Select labels"
                                                uncountableItems={filteredLabels.slice(0, 2).map((label) => label.uid)}
                                                filterName="labels"
                                                createFilterItems={() =>
                                                    filteredLabels.slice(2).map((label) => (
                                                        <BoardFilterItem key={`board-filter-label-${label.uid}`} name="labels" value={label.uid}>
                                                            <BoardLabelListItem label={label} />
                                                        </BoardFilterItem>
                                                    ))
                                                }
                                            />
                                        )}
                                    </Flex>
                                </Flex>
                            )}
                            {category === "relationships" &&
                                (["parents", "children"] as (keyof IFilterMap)[]).map((relationship) => (
                                    <Flex direction="col" key={`board-filter-${relationship}`}>
                                        <Label>{t(`board.filters.relationships.${relationship}`)}</Label>
                                        <BoardExtendedFilter
                                            filterLangLabel="Select cards"
                                            filterName={relationship}
                                            createFilterItems={() =>
                                                cards
                                                    .filter(
                                                        (card) =>
                                                            card.relationships.filter(
                                                                (cardRelationship) =>
                                                                    (relationship === "parents"
                                                                        ? cardRelationship.child_card_uid
                                                                        : cardRelationship.parent_card_uid) === card.uid
                                                            ).length > 0
                                                    )
                                                    .filter((card) => filterCard(card))
                                                    .map((card) => (
                                                        <BoardFilterItem
                                                            key={`board-filter-${relationship}-${card.uid}`}
                                                            name={relationship}
                                                            value={card.uid}
                                                        >
                                                            <span>{card.title}</span>
                                                        </BoardFilterItem>
                                                    ))
                                            }
                                        />
                                    </Flex>
                                ))}
                        </div>
                    </div>
                    <p className="border-t px-3 py-2 text-xs text-muted-foreground">{t("board.filters.Combination guidance")}</p>
                </Popover.Content>
            </Popover.Root>
            {countAppliedFilters > 0 && (
                <>
                    <div aria-label={t("board.filters.Applied filters")} className="flex max-w-full flex-wrap gap-1">
                        {(Object.keys(filters) as (keyof IFilterMap)[]).flatMap((name) =>
                            (filters[name] ?? []).map((value) => (
                                <Button
                                    key={`${name}:${value}`}
                                    variant="ghost"
                                    size="sm"
                                    title={filterTitle(name, value)}
                                    aria-label={`${t("board.filters.Remove filter")}: ${filterTitle(name, value)}`}
                                    className="h-7 max-w-44 gap-1 rounded-full bg-accent/55 px-2 text-xs"
                                    onClick={() => removeFilter(name, value)}
                                >
                                    <span className="truncate">{filterTitle(name, value)}</span>
                                    <IconComponent icon="x" className="size-3 shrink-0" />
                                </Button>
                            ))
                        )}
                    </div>
                    <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={clearFilters}>
                        {t("board.filters.Clear")}
                    </Button>
                </>
            )}
        </div>
    );
}
BoardFilter.displayName = "Board.Filter";

interface IBoardFilterExtendedProps {
    filterLangLabel: string;
    uncountableItems?: string[];
    filterName: keyof IFilterMap;
    createFilterItems: () => React.ReactNode;
}

function BoardExtendedFilter({ filterLangLabel, uncountableItems, filterName, createFilterItems }: IBoardFilterExtendedProps) {
    const { project, filters, navigateWithFilters } = useBoard();
    const [t, i18n] = useTranslation();

    const countSelections = filters[filterName]?.filter((v) => !(uncountableItems ?? []).includes(v)).length ?? 0;

    const clearSelection = () => {
        filters[filterName] = [];

        navigateWithFilters(ROUTES.BOARD.MAIN(project.uid));
    };

    return (
        <div className="flex flex-col">
            <div className="mt-2 flex items-center justify-between gap-2 px-3 text-xs text-muted-foreground">
                <span>
                    {t(`board.filters.${filterLangLabel}`)}
                    {countSelections > 0 && ` (${formatNumber(countSelections, i18n.language)})`}
                </span>
                {countSelections > 0 && (
                    <Button variant="ghost" size="sm" className="h-7 px-1 text-xs" onClick={clearSelection}>
                        {t("board.filters.Clear selections")}
                    </Button>
                )}
            </div>
            {createFilterItems()}
        </div>
    );
}
BoardExtendedFilter.displayName = "Board.ExtendedFilter";

function CreatorChoice({ creatorKey, name }: { creatorKey: string; name: string }) {
    const { project, cards } = useBoard();
    const member = project.all_members.find((item) => `user/${item.uid}` === creatorKey);
    if (member) return <UserAvatar.Root userOrBot={member} withNameProps={{ className: "gap-1" }} avatarSize="xs" />;
    const creator = cards.find((item) => item.creator && `${item.creator.type}/${item.creator.uid}` === creatorKey)?.creator;
    return (
        <span className="flex min-w-0 items-center gap-1">
            <Avatar.Root size="xs">
                <Avatar.Image src={creator?.avatar ?? undefined} alt={name} />
                <Avatar.Fallback>{name.slice(0, 2) || "?"}</Avatar.Fallback>
            </Avatar.Root>
            <span>{name}</span>
        </span>
    );
}

interface IBoardFilterItemProps {
    name: keyof IFilterMap;
    value: string;
    children: React.ReactNode;
}

function BoardFilterItem({ name, value, children }: IBoardFilterItemProps) {
    const { project, filters, navigateWithFilters } = useBoard();
    const checked = useMemo(() => !!filters[name] && filters[name].includes(value), [filters, filters[name]]);

    const setFilterCards = (checked: CheckedState) => {
        if (!filters[name]) {
            filters[name] = [];
        }

        if (checked) {
            filters[name].push(value);
        } else {
            filters[name] = filters[name].filter((filter) => filter !== value);
        }

        navigateWithFilters(ROUTES.BOARD.MAIN(project.uid));
    };

    return (
        <Label display="flex" cursor="pointer" items="center" gap="2" p="3" className="hover:bg-accent/80">
            <Checkbox name={name as string} checked={checked} onCheckedChange={setFilterCards} />
            {children}
        </Label>
    );
}
BoardFilterItem.displayName = "Board.FilterItem";

export default BoardFilter;
