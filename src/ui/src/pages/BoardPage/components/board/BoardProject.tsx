import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import useGetCards from "@/controllers/api/board/useGetCards";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ROUTES } from "@/core/routing/constants";
import BoardFilter from "@/pages/BoardPage/components/board/BoardFilter";
import BoardSort from "@/pages/BoardPage/components/board/BoardSort";
import { memo, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { BoardProvider } from "@/core/providers/BoardProvider";
import BoardMemberList from "@/pages/BoardPage/components/board/BoardMemberList";
import { AuthUser, Project } from "@/core/models";
import { useBoardController } from "@/core/providers/BoardController";
import { Board, SkeletonBoard } from "@/pages/BoardPage/components/board/Board";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { EHttpStatus } from "@langboard/core/enums";

export interface IBoardProps {
    project: Project.TModel;
    currentUser: AuthUser.TModel;
}

const BoardProject = memo(({ project, currentUser }: IBoardProps) => {
    const navigate = usePageNavigateRef();
    const { data, error } = useGetCards({ project_uid: project.uid });

    useEffect(() => {
        if (!error) {
            return;
        }

        const { handle } = setupApiErrorHandler({
            [EHttpStatus.HTTP_403_FORBIDDEN]: {
                after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_403_FORBIDDEN), { replace: true }),
            },
            [EHttpStatus.HTTP_404_NOT_FOUND]: {
                after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND), { replace: true }),
            },
        });

        handle(error);
    }, [error]);

    return (
        <>
            {!data ? (
                <SkeletonBoard />
            ) : (
                <BoardProvider project={project} currentUser={currentUser}>
                    <BoardResult key={`board-result-${project.uid}`} project={project} />
                </BoardProvider>
            )}
        </>
    );
});
BoardProject.displayName = "BoardProject";

const BoardResult = memo(({ project }: { project: Project.TModel }) => {
    const { selectCardViewType, selectedRelationshipUIDs, saveCardSelection, cancelCardSelection } = useBoardController();
    const [t] = useTranslation();

    return (
        <>
            {selectCardViewType && (
                <Flex justify="center" items="center" position="fixed" top="-2" left="0" h="20" w="full" z="50" gap="3" px="1">
                    <Box position="absolute" top="0" left="0" size="full" className="bg-secondary/70 bg-cover blur-md backdrop-blur-sm" />
                    <Flex wrap position="relative" z="50" textSize={{ initial: "base", sm: "lg" }} weight="semibold" className="text-primary">
                        <Box mr="2">{t(`board.Select ${selectCardViewType === "parents" ? "parent" : "child"} cards`)}</Box>
                        {selectedRelationshipUIDs.length > 0 && (
                            <Box>({t("board.{count} selected", { count: selectedRelationshipUIDs.length })})</Box>
                        )}
                    </Flex>
                    <Flex wrap position="relative" justify="end" z="50" className="text-right">
                        <Button
                            type="button"
                            variant="secondary"
                            className="mb-1 mr-2 h-6 px-2 py-0 sm:mb-0 sm:h-8 sm:px-4"
                            onClick={cancelCardSelection}
                        >
                            {t("common.Cancel")}
                        </Button>
                        <Button type="button" className="mr-2 h-6 px-2 py-0 sm:h-8 sm:px-4" onClick={saveCardSelection}>
                            {t("common.Save")}
                        </Button>
                    </Flex>
                </Flex>
            )}

            <Flex justify="between" px="4" pt="4" wrap>
                <BoardMemberList isSelectCardView={!!selectCardViewType} />
                <Flex items="center" gap="1">
                    <BoardFilter />
                    <BoardSort />
                </Flex>
            </Flex>

            <Board key={`board-${project.uid}`} />
        </>
    );
});
BoardResult.displayName = "Board.Result";

export default BoardProject;
