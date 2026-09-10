import { memo, useMemo, useReducer, useState } from "react";
import { useTranslation } from "react-i18next";
import Card from "@/components/base/Card";
import Flex from "@/components/base/Flex";
import Skeleton from "@/components/base/Skeleton";
import { ROUTES } from "@/core/routing/constants";
import { Utils } from "@langboard/core/utils";
import { Project, ProjectColumn } from "@/core/models";
import { useDashboard } from "@/core/providers/DashboardProvider";
import ProjectItemColumn from "@/pages/DashboardPage/components/ProjectItemColumn";
import ProjectItemStarButton from "@/pages/DashboardPage/components/ProjectItemStarButton";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { cn } from "@/core/utils/ComponentUtils";
import useDashboardProjectUIColumnOrderChangedHandlers from "@/controllers/socket/dashboard/project/useDashboardProjectUIColumnOrderChangedHandlers";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";

export const SkeletonProjectItem = memo(() => {
    const cards = [];
    for (let i = 0; i < 6; ++i) {
        cards.push({
            type: null,
            subcards: <Skeleton display="inline-block" h="3.5" className="w-3/4" />,
            color: <Skeleton display="inline-block" h="0.5" w="full" rounded="full" />,
        });
    }

    return (
        <Card.Root className="border-transparent shadow-transparent">
            <Card.Header className="relative block pt-5">
                <Card.Title className="max-w-[calc(100%_-_theme(spacing.8))] text-sm leading-tight text-gray-500">
                    <Skeleton display="inline-block" h="3.5" className="w-1/2" />
                </Card.Title>
                <Card.Title className="max-w-[calc(100%_-_theme(spacing.8))] leading-tight">
                    <Skeleton display="inline-block" h="4" className="w-3/4" />
                </Card.Title>
                <Skeleton position="absolute" right="2.5" top="1" display="inline-block" size="9" />
            </Card.Header>
            <Card.Content></Card.Content>
            <Card.Footer className="flex items-center gap-1.5">
                {cards.map((card) => (
                    <Flex direction="col" items="center" gap="0.5" minW="5" key={Utils.String.Token.shortUUID()}>
                        {card.subcards}
                        {card.color}
                    </Flex>
                ))}
            </Card.Footer>
        </Card.Root>
    );
});

export interface IProjectItemProps extends React.ComponentPropsWithoutRef<typeof Card.Root> {
    project: Project.TModel;
    updateStarredProjects: React.DispatchWithoutAction;
}

const ProjectItem = memo(({ project, updateStarredProjects, ...props }: IProjectItemProps): React.JSX.Element => {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const { socket } = useDashboard();
    const [isUpdating, setIsUpdating] = useState(false);
    const title = project.useField("title");
    const projectType = project.useField("project_type");
    const flatColumns = ProjectColumn.Model.useModels((model) => model.project_uid === project.uid);
    const [updated, forceUpdate] = useReducer((x) => x + 1, 0);
    const columns = useMemo(() => flatColumns.sort((a, b) => a.order - b.order), [flatColumns, updated]);
    const handlers = useMemo(
        () =>
            useDashboardProjectUIColumnOrderChangedHandlers({
                projectUID: project.uid,
                callback: () => {
                    forceUpdate();
                },
            }),
        [forceUpdate]
    );
    useSwitchSocketHandlers({ socket, handlers, dependencies: [handlers] });

    const toBoard = () => {
        if (!project) {
            return;
        }

        navigate(ROUTES.BOARD.MAIN(project.uid));
    };

    return (
        <Card.Root {...props} className={cn(props.className, "cursor-pointer")} onClick={toBoard}>
            <ModelRegistry.Project.Provider model={project}>
                <Card.Header className="relative block pt-5">
                    <Card.Title className="max-w-[calc(100%_-_theme(spacing.8))] text-sm leading-tight text-gray-500">
                        {t(projectType === "Other" ? "common.Other" : `project.types.${projectType}`)}
                    </Card.Title>
                    <Card.Title className="max-w-[calc(100%_-_theme(spacing.8))] leading-tight">{title}</Card.Title>
                    <ProjectItemStarButton isUpdating={isUpdating} setIsUpdating={setIsUpdating} updateStarredProjects={updateStarredProjects} />
                </Card.Header>
                <Card.Content></Card.Content>
                <Card.Footer className="flex items-center gap-1.5">
                    {columns.map((column) => (
                        <ProjectItemColumn key={column.uid} column={column} />
                    ))}
                </Card.Footer>
            </ModelRegistry.Project.Provider>
        </Card.Root>
    );
});

export default ProjectItem;
