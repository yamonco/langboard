import Button from "@/components/base/Button";
import Checkbox from "@/components/base/Checkbox";
import DropdownMenu from "@/components/base/DropdownMenu";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Input from "@/components/base/Input";
import Label from "@/components/base/Label";
import Popover from "@/components/base/Popover";
import ScrollArea from "@/components/base/ScrollArea";
import Skeleton from "@/components/base/Skeleton";
import UserAvatar from "@/components/UserAvatar";
import { IFilterMap, useBoard } from "@/core/providers/BoardProvider";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import BoardLabelListItem from "@/pages/BoardPage/components/board/BoardLabelListItem";
import { CheckedState } from "@radix-ui/react-checkbox";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export function SkeletonBoardFilter() {
    return <Skeleton h="9" w={{ initial: "7", xs: "14" }} px={{ xs: "4" }} />;
}

function BoardFilter() {
    const { project, columns, cards, currentUser, filters, filterCard, filterMember, filterLabel, navigateWithFilters } = useBoard();
    const [t] = useTranslation();
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

    const setFilterKeyword = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (!filters.keyword) {
            filters.keyword = [];
        }

        const keyword = event.currentTarget.value;

        if (filters.keyword.includes(keyword)) {
            return;
        }

        filters.keyword = keyword.split(",");

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

    return (
        <Popover.Root>
            <Popover.Trigger asChild>
                <Flex items="center">
                    <Button
                        variant="ghost"
                        aria-label={t("board.Filters")}
                        className={cn("gap-1 px-2 text-xs xs:px-4 xs:text-sm", countAppliedFilters > 0 ? "rounded-e-none bg-accent/55 xs:pr-2" : "")}
                    >
                        <IconComponent icon="filter" size={{ initial: "3", xs: "4" }} />
                        <span className="hidden xs:inline-block">{t("board.Filters")}</span>
                        {countAppliedFilters > 0 && <span className="pb-1 xs:pb-0.5">{` (${countAppliedFilters})`}</span>}
                    </Button>
                    {countAppliedFilters > 0 && (
                        <Button variant="ghost" className="rounded-s-none bg-accent/55 px-2 py-1 text-xs xs:pr-4 xs:text-sm" onClick={clearFilters}>
                            <span className="pb-0.5 xs:pb-0">{t("board.filters.Clear")}</span>
                        </Button>
                    )}
                </Flex>
            </Popover.Trigger>
            <Popover.Content align="end" className="max-w-[calc(var(--radix-popper-available-width)_-_theme(spacing.4))]">
                <ScrollArea.Root>
                    <Flex direction="col" gap="4" className="max-h-[calc(100vh_-_theme(spacing.40))]">
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
                        <Label display="block">
                            <span>{t("board.filters.Keyword")}</span>
                            <Input
                                className="mx-1 mt-2 w-[calc(100%_-_theme(spacing.2))]"
                                defaultValue={filters.keyword?.join(",")}
                                onKeyUp={setFilterKeyword}
                            />
                        </Label>
                        <Flex direction="col">
                            <Label>{t("board.filters.Assignee")}</Label>
                            <Flex direction="col" pt="1">
                                <BoardFilterItem name="members" value="none">
                                    <span>{t("board.filters.No members assigned")}</span>
                                </BoardFilterItem>
                                <BoardFilterItem name="members" value="me">
                                    <span>{t("board.filters.Assigned to me")}</span>
                                </BoardFilterItem>
                                <BoardExtendedFilter
                                    filterLangLabel="Select members"
                                    uncountableItems={["none", "me"]}
                                    filterName="members"
                                    createFilterItems={() =>
                                        project.all_members
                                            .filter(
                                                (member) =>
                                                    member.isValidUser() && !project.invited_member_uids.includes(member.uid) && filterMember(member)
                                            )
                                            .map((member) => (
                                                <BoardFilterItem key={`board-filter-member-${member.uid}`} name="members" value={member.email}>
                                                    <UserAvatar.Root userOrBot={member} withNameProps={{ className: "gap-1" }} avatarSize="xs" />
                                                </BoardFilterItem>
                                            ))
                                    }
                                />
                            </Flex>
                        </Flex>
                        <Flex direction="col">
                            <Label>{t("board.filters.Creator")}</Label>
                            <BoardFilterItem name="creators" value="me">
                                <span>{t("board.filters.Created by me")}</span>
                            </BoardFilterItem>
                            <BoardExtendedFilter
                                filterLangLabel="Select creators"
                                uncountableItems={["me"]}
                                filterName="creators"
                                createFilterItems={() =>
                                    creators.map(([key, name]) => (
                                        <BoardFilterItem key={key} name="creators" value={key}>
                                            <IconComponent icon="pencil" size="4" />
                                            <span>{name || t("common.Unknown")}</span>
                                        </BoardFilterItem>
                                    ))
                                }
                            />
                        </Flex>
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
                        {(["parents", "children"] as (keyof IFilterMap)[]).map((relationship) => (
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
                    </Flex>
                </ScrollArea.Root>
            </Popover.Content>
        </Popover.Root>
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
    const [t] = useTranslation();

    const countSelections = filters[filterName]?.filter((v) => !(uncountableItems ?? []).includes(v)).length ?? 0;

    const clearSelection = () => {
        filters[filterName] = [];

        navigateWithFilters(ROUTES.BOARD.MAIN(project.uid));
    };

    return (
        <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
                <Button
                    variant="ghost"
                    className={cn(
                        "group/extension mt-1 justify-between rounded-none p-3 hover:bg-accent/80",
                        countSelections > 0 ? "bg-accent/55" : ""
                    )}
                >
                    <span>
                        {t(`board.filters.${filterLangLabel}`)}
                        {countSelections > 0 && ` (${countSelections})`}
                    </span>
                    <IconComponent
                        icon="chevron-down"
                        size="4"
                        className="transition-transform duration-200 group-data-[state=open]/extension:rotate-180"
                    />
                </Button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="start" className="flex flex-col p-0">
                <ScrollArea.Root>
                    <Flex
                        direction="col"
                        pr="2.5"
                        position="relative"
                        minW="56"
                        className={cn(countSelections > 0 ? "max-h-[calc(theme(spacing.56)_-_theme(spacing.1))]" : "max-h-64")}
                    >
                        {createFilterItems()}
                    </Flex>
                </ScrollArea.Root>
                {countSelections > 0 && (
                    <Button
                        variant="ghost"
                        className="sticky bottom-0 left-0 z-10 gap-2 rounded-none bg-background p-3 pr-5 hover:bg-accent/80"
                        onClick={clearSelection}
                    >
                        <IconComponent icon="x" size="4" />
                        {t("board.filters.Clear selections")}
                    </Button>
                )}
            </DropdownMenu.Content>
        </DropdownMenu.Root>
    );
}
BoardExtendedFilter.displayName = "Board.ExtendedFilter";

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
