import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import { Project } from "@/core/models";
import ProjectCompactItem from "@/pages/DashboardPage/components/ProjectCompactItem";
import InfiniteScroller from "@/components/InfiniteScroller";
import useInfiniteScrollPager from "@/core/hooks/useInfiniteScrollPager";
import Skeleton from "@/components/base/Skeleton";
import Button from "@/components/base/Button";
import { cn } from "@/core/utils/ComponentUtils";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

interface IProjectCompactListProps {
    projects: Project.TModel[];
    title?: string;
    initialVisibleCount?: number;
    listClassName?: string;
    dense?: boolean;
    updateStarredProjects: React.DispatchWithoutAction;
}

const ProjectCompactList = ({
    projects,
    title,
    updateStarredProjects,
    initialVisibleCount,
    listClassName,
    dense,
}: IProjectCompactListProps): React.JSX.Element | null => {
    const [t] = useTranslation();
    const listId = useId();
    const [expanded, setExpanded] = useState(false);
    const { items, nextPage } = useInfiniteScrollPager({ allItems: projects, size: 24 });
    if (!projects.length) return null;
    const visibleProjects = initialVisibleCount ? (expanded ? projects : projects.slice(0, initialVisibleCount)) : items;
    const rows = visibleProjects.map((project) => (
        <ProjectCompactItem key={project.uid} project={project} updateStarredProjects={updateStarredProjects} dense={dense} />
    ));
    const listClasses = cn("grid gap-1 rounded-2xl border bg-card/60 p-1.5", listClassName);

    return (
        <Box className="mt-4 min-w-0" role={title ? "region" : undefined} aria-label={title}>
            {title ? (
                <Flex items="baseline" gap="2" className="mb-2 px-1">
                    <h2 className="text-sm font-semibold">{title}</h2>
                    <span className="text-xs tabular-nums text-muted-foreground">{projects.length}</span>
                    {initialVisibleCount && projects.length > initialVisibleCount ? (
                        <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="ml-auto h-6 px-2 text-xs"
                            aria-expanded={expanded}
                            aria-controls={listId}
                            onClick={() => setExpanded((value) => !value)}
                        >
                            {expanded ? t("editor.Show less") : `${t("editor.Show more")} (+${projects.length - initialVisibleCount})`}
                        </Button>
                    ) : null}
                </Flex>
            ) : null}
            {initialVisibleCount ? (
                <Box id={listId} className={cn(listClasses, "max-h-64 overflow-y-auto")}>
                    {rows}
                </Box>
            ) : (
                <InfiniteScroller.NoVirtual
                    as={Box}
                    className={listClasses}
                    hasMore={items.length < projects.length}
                    loadMore={nextPage}
                    scrollable={() => document.getElementById("main")}
                    loader={<Skeleton className="h-16 w-full" />}
                >
                    {rows}
                </InfiniteScroller.NoVirtual>
            )}
        </Box>
    );
};

export default ProjectCompactList;
