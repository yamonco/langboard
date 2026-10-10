import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import { Project } from "@/core/models";
import ProjectCompactItem from "@/pages/DashboardPage/components/ProjectCompactItem";
import InfiniteScroller from "@/components/InfiniteScroller";
import useInfiniteScrollPager from "@/core/hooks/useInfiniteScrollPager";
import Skeleton from "@/components/base/Skeleton";

interface IProjectCompactListProps {
    projects: Project.TModel[];
    title?: string;
    updateStarredProjects: React.DispatchWithoutAction;
}

const ProjectCompactList = ({ projects, title, updateStarredProjects }: IProjectCompactListProps): React.JSX.Element | null => {
    const { items, nextPage } = useInfiniteScrollPager({ allItems: projects, size: 24 });
    if (!projects.length) return null;

    return (
        <Box className="mt-4">
            {title ? (
                <Flex items="baseline" gap="2" className="mb-2 px-1">
                    <h2 className="text-sm font-semibold">{title}</h2>
                    <span className="text-xs tabular-nums text-muted-foreground">{projects.length}</span>
                </Flex>
            ) : null}
            <InfiniteScroller.NoVirtual
                as={Box}
                className="grid gap-1 rounded-2xl border bg-card/60 p-1.5"
                hasMore={items.length < projects.length}
                loadMore={nextPage}
                scrollable={() => document.getElementById("main")}
                loader={<Skeleton className="h-16 w-full" />}
            >
                {items.map((project) => (
                    <ProjectCompactItem key={project.uid} project={project} updateStarredProjects={updateStarredProjects} />
                ))}
            </InfiniteScroller.NoVirtual>
        </Box>
    );
};

export default ProjectCompactList;
