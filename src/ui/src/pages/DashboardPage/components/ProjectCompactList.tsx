import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import { Project } from "@/core/models";
import ProjectCompactItem from "@/pages/DashboardPage/components/ProjectCompactItem";
import type { TProjectActivityKind } from "@/pages/DashboardPage/components/ProjectActivityPriority";

interface IProjectCompactListProps {
    activityKind?: TProjectActivityKind;
    projects: Project.TModel[];
    title?: string;
    updateStarredProjects: React.DispatchWithoutAction;
}

const ProjectCompactList = ({
    activityKind = "project",
    projects,
    title,
    updateStarredProjects,
}: IProjectCompactListProps): React.JSX.Element | null => {
    if (!projects.length) return null;

    return (
        <Box className="mt-4">
            {title ? (
                <Flex items="baseline" gap="2" className="mb-2 px-1">
                    <h2 className="text-sm font-semibold">{title}</h2>
                    <span className="text-xs tabular-nums text-muted-foreground">{projects.length}</span>
                </Flex>
            ) : null}
            <Box className="grid gap-1 rounded-2xl border bg-card/60 p-1.5 md:grid-cols-2 xl:grid-cols-3">
                {projects.map((project) => (
                    <ProjectCompactItem
                        key={project.uid}
                        activityKind={activityKind}
                        project={project}
                        updateStarredProjects={updateStarredProjects}
                    />
                ))}
            </Box>
        </Box>
    );
};

export default ProjectCompactList;
