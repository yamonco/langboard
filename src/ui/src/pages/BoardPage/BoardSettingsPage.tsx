import { memo, useEffect } from "react";
import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import Skeleton from "@/components/base/Skeleton";
import { ROUTES } from "@/core/routing/constants";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { IBoardRelatedPageProps } from "@/pages/BoardPage/types";
import useGetProjectDetails from "@/controllers/api/board/useGetProjectDetails";
import BoardSettingsList from "@/pages/BoardPage/components/settings/BoardSettingsList";
import { BoardSettingsProvider } from "@/core/providers/BoardSettingsProvider";
import BoardSettingsUserList from "@/pages/BoardPage/components/settings/BoardSettingsUserList";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { EHttpStatus } from "@langboard/core/enums";

export function SkeletonBoardSettingsPage(): React.JSX.Element {
    return (
        <Flex direction="col" gap="3" p={{ initial: "4", md: "6", lg: "8" }} items="center">
            <Box w="full" className="max-w-screen-sm">
                <Skeleton h="8" mb="2" className="scroll-m-20" />
                <Box items="center" justify="center" py="4" gap="2" w="full" wrap display={{ initial: "hidden", sm: "flex" }}>
                    <Skeleton h="6" className="w-1/5" />
                    <Skeleton h="6" className="w-1/5" />
                    <Skeleton h="6" className="w-1/5" />
                    <Skeleton h="6" className="w-1/5" />
                </Box>
            </Box>
        </Flex>
    );
}

const BoardSettingsPage = memo(({ project, currentUser }: IBoardRelatedPageProps) => {
    const { data, error } = useGetProjectDetails({ uid: project.uid });
    const navigate = usePageNavigateRef();

    useEffect(() => {
        if (!error) {
            return;
        }

        const { handle } = setupApiErrorHandler({
            [EHttpStatus.HTTP_403_FORBIDDEN]: {
                toast: false,
            },
            [EHttpStatus.HTTP_404_NOT_FOUND]: {
                after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND), { replace: true }),
            },
        });

        handle(error);
    }, [error]);

    return (
        <Box className="h-full min-h-0 overflow-y-auto">
            <BoardSettingsUserList currentUser={currentUser} project={project} />
            {data && (
                <BoardSettingsProvider project={project} currentUser={currentUser}>
                    <BoardSettingsList />
                </BoardSettingsProvider>
            )}
        </Box>
    );
});

export default BoardSettingsPage;
