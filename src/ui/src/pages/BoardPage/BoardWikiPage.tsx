import useGetWikis from "@/controllers/api/wiki/useGetWikis";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { BoardWikiProvider } from "@/core/providers/BoardWikiProvider";
import { useSocket } from "@/core/providers/SocketProvider";
import { ROUTES } from "@/core/routing/constants";
import { BoardWikiUnsavedProvider } from "@/pages/BoardPage/components/wiki/BoardWikiUnsavedProvider";
import WikiList, { SkeletonWikiList } from "@/pages/BoardPage/components/wiki/WikiList";
import { IBoardRelatedPageProps } from "@/pages/BoardPage/types";
import { EHttpStatus, ESocketTopic } from "@langboard/core/enums";
import { memo, useEffect } from "react";

export function SkeletonBoardWikiPage(): React.JSX.Element {
    return <SkeletonWikiList />;
}

const BoardWikiPage = memo(({ project, currentUser }: IBoardRelatedPageProps) => {
    const socket = useSocket();
    const navigate = usePageNavigateRef();
    const { data, error } = useGetWikis({ project_uid: project.uid });

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

    useEffect(() => {
        if (!data) {
            return;
        }

        socket.subscribe(ESocketTopic.BoardWiki, [project.uid]);
        socket.subscribe(
            ESocketTopic.BoardWikiPrivate,
            data.wikis.map((wiki) => wiki.uid)
        );

        return () => {
            socket.unsubscribe(ESocketTopic.BoardWiki, [project.uid]);
            socket.unsubscribe(
                ESocketTopic.BoardWikiPrivate,
                data.wikis.map((wiki) => wiki.uid)
            );
        };
    }, [data, project]);

    return (
        <>
            {!data ? (
                <SkeletonWikiList />
            ) : (
                <BoardWikiProvider key={project.uid} project={project} projectMembers={data.project_members} currentUser={currentUser}>
                    <BoardWikiUnsavedProvider>
                        <WikiList />
                    </BoardWikiUnsavedProvider>
                </BoardWikiProvider>
            )}
        </>
    );
});

export default BoardWikiPage;
