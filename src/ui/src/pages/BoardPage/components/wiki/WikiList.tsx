import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Skeleton from "@/components/base/Skeleton";
import Tabs from "@/components/base/Tabs";
import useGrabbingScrollHorizontal from "@/core/hooks/useGrabbingScrollHorizontal";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ProjectWiki } from "@/core/models";
import { useBoardWiki } from "@/core/providers/BoardWikiProvider";
import { ROUTES } from "@/core/routing/constants";
import { getEditorStore } from "@/core/stores/EditorStore";
import WikiContent, { SkeletonWikiContent } from "@/pages/BoardPage/components/wiki/WikiContent";
import WikiCreateButton from "@/pages/BoardPage/components/wiki/WikiCreateButton";
import WikiEmptyState from "@/pages/BoardPage/components/wiki/WikiEmptyState";
import WikiTabList, { SkeletonWikiTabList } from "@/pages/BoardPage/components/wiki/WikiTabList";
import { memo, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

export function SkeletonWikiList() {
    return (
        <Box p="2">
            <Flex items="center" justify="between" gap="1">
                <SkeletonWikiTabList />
                <Flex h="full" pb="2" gap="1">
                    <Skeleton size="8" />
                    <Skeleton size="8" />
                </Flex>
            </Flex>
            <SkeletonWikiContent />
        </Box>
    );
}

const WikiList = memo(() => {
    const { wikiUID } = useParams();
    const navigate = usePageNavigateRef();
    const { project, canAccessWiki, wikis } = useBoardWiki();

    // Auto-select: Redirect to first accessible wiki when no wikiUID and wikis exist
    useEffect(() => {
        if (!wikiUID && wikis.length > 0) {
            const firstAccessibleWiki = wikis.find((wiki) => canAccessWiki(false, wiki.uid));
            if (firstAccessibleWiki) {
                navigate(ROUTES.BOARD.WIKI_PAGE(project.uid, firstAccessibleWiki.uid));
                return;
            }
        }
    }, [wikiUID, wikis]);

    useEffect(() => {
        if (!canAccessWiki(true, wikiUID)) {
            getEditorStore().setCurrentEditor(null);
            navigate(ROUTES.BOARD.WIKI(project.uid));
        }
    }, [wikiUID]);

    return (
        <Tabs.Provider value={wikiUID}>
            <WikiListDisplay wikiUID={wikiUID} />
        </Tabs.Provider>
    );
});

interface IWikiListDisplayProps {
    wikiUID?: string;
}

function WikiListDisplay({ wikiUID }: IWikiListDisplayProps) {
    const [t] = useTranslation();
    const { project, wikis, canAccessWiki, modeType, setModeType, wikiTabListId } = useBoardWiki();
    const { updateUI } = Tabs.useTabsContext();
    const { onPointerDown } = useGrabbingScrollHorizontal(wikiTabListId);
    const handleDeleteMode = useCallback(() => {
        setModeType(modeType === "delete" ? "view" : "delete");
    }, [modeType, setModeType]);
    const handleReorderMode = useCallback(() => {
        setModeType(modeType === "reorder" ? "view" : "reorder");
    }, [modeType, setModeType]);
    const activeWiki = wikis.find((wiki) => wiki.uid === wikiUID && canAccessWiki(false, wiki.uid));

    useEffect(() => {
        setTimeout(() => {
            updateUI();
        }, 200);
    }, [modeType, wikis]);

    if (wikis.length === 0) {
        return (
            <Box p="2">
                <WikiEmptyState />
            </Box>
        );
    }

    return (
        <Box p="2">
            <nav aria-label={t("common.Breadcrumb")} className="mb-2 flex min-w-0 items-center gap-2 px-1 text-xs text-muted-foreground">
                <Link to={ROUTES.BOARD.MAIN(project.uid)} className="hover:text-foreground hover:underline">
                    {t("board.Board")}
                </Link>
                <span aria-hidden="true">/</span>
                <span>{t("board.Wiki")}</span>
                {activeWiki && (
                    <>
                        <span aria-hidden="true">/</span>
                        <WikiBreadcrumbTitle key={activeWiki.uid} wiki={activeWiki} />
                    </>
                )}
            </nav>
            <Flex items="center" justify="between" gap="1">
                <Box id={wikiTabListId} pb="0.5" w="full" className="max-w-[calc(100%_-_theme(spacing.20))] overflow-x-scroll">
                    <Tabs.List className="justify-start gap-1 border-none p-0" onPointerDown={onPointerDown}>
                        <WikiTabList />
                    </Tabs.List>
                </Box>
                <Flex h="full" pb="2" gap="1">
                    <Button
                        variant={modeType !== "delete" ? "ghost" : "default"}
                        size="icon-sm"
                        title={t("wiki.Toggle delete mode")}
                        titleAlign="end"
                        onClick={handleDeleteMode}
                    >
                        <IconComponent icon="trash-2" size="4" />
                    </Button>
                    <Button
                        variant={modeType !== "reorder" ? "ghost" : "default"}
                        size="icon-sm"
                        title={t("wiki.Toggle reorder mode")}
                        titleAlign="end"
                        onClick={handleReorderMode}
                    >
                        <IconComponent icon="replace-all" size="4" />
                    </Button>
                    <WikiCreateButton />
                </Flex>
            </Flex>
            {wikis.map((wiki) =>
                wikiUID === wiki.uid && canAccessWiki(false, wiki.uid) ? (
                    <Tabs.Content key={`board-wiki-${wiki.uid}-content`} value={wiki.uid}>
                        <WikiContent wiki={wiki} />
                    </Tabs.Content>
                ) : null
            )}
        </Box>
    );
}

function WikiBreadcrumbTitle({ wiki }: { wiki: ProjectWiki.TModel }) {
    const title = wiki.useField("title");
    return (
        <span className="min-w-0 truncate text-foreground" aria-current="page">
            {title}
        </span>
    );
}

export default WikiList;
