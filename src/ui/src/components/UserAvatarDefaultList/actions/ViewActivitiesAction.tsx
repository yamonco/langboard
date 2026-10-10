/* eslint-disable @typescript-eslint/no-explicit-any */
import Popover from "@/components/base/Popover";
import { AuthUser, Project } from "@/core/models";
import SuspenseComponent from "@/components/base/SuspenseComponent";
import { useTranslation } from "react-i18next";
import { lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useUserAvatar } from "@/components/UserAvatar/Provider";
import UserAvatar from "@/components/UserAvatar";
import useHandleInteractOutside from "@/core/hooks/useHandleInteractOutside";
import { IUserAvatarDefaultListContext } from "@/components/UserAvatarDefaultList/Provider";
import { TActivityType } from "@/controllers/api/shared/types";

const ActivityList = lazy(() => import("@/components/ActivityList"));

export interface IUserAvatarDefaultViewActivitiesActionProps {
    scopeModels: Required<IUserAvatarDefaultListContext["scopeModels"]> & { project: Project.TModel };
    currentUser: AuthUser.TModel;
}

function UserAvatarDefaultViewActivitiesAction({ scopeModels, currentUser }: IUserAvatarDefaultViewActivitiesActionProps): React.JSX.Element | null {
    const { userOrBot, getAvatarHoverCardAttrs } = useUserAvatar();
    const [t] = useTranslation();
    const triggerRef = useRef<HTMLDivElement>(null);
    const [isOpened, setIsOpened] = useState(false);
    const [maxHeight, setMaxHeight] = useState("0px");
    const [side, setSide] = useState<React.ComponentProps<typeof Popover.Content>["side"]>("bottom");
    const style = {
        "--max-height": maxHeight,
    };
    const activityForm = useMemo(() => {
        const form: Record<string, string> = { project_uid: scopeModels.project.uid };
        let scopeType: TActivityType = "project";

        if (scopeModels.column) {
            scopeType = "project_column";
            form.project_column_uid = scopeModels.column.uid;
        }

        if (scopeModels.card) {
            scopeType = "card";
            form.card_uid = scopeModels.card.uid;
        }

        if (scopeModels.wiki) {
            scopeType = "project_wiki";
            form.wiki_uid = scopeModels.wiki.uid;
        }

        return { listType: "ActivityModel", type: scopeType, assignee_uid: userOrBot.uid, ...form };
    }, [scopeModels]);
    const checkSize = useCallback(() => {
        if (!triggerRef.current || !isOpened) {
            return;
        }

        const rect = triggerRef.current.getBoundingClientRect();
        const MAX_HEIGHT = 500;
        const PADDING_SIZE = 16;
        const topSideHeight = rect.top - PADDING_SIZE;
        const bottomSideHeight = document.body.scrollHeight - rect.bottom - PADDING_SIZE;

        let futureMaxHeight: number;
        let futureSide: React.ComponentProps<typeof Popover.Content>["side"];

        if (rect.bottom + MAX_HEIGHT <= document.body.scrollHeight) {
            futureMaxHeight = MAX_HEIGHT;
            futureSide = "bottom";
        } else if (rect.top - MAX_HEIGHT >= 0) {
            futureMaxHeight = MAX_HEIGHT;
            futureSide = "top";
        } else {
            futureMaxHeight = Math.max(topSideHeight, bottomSideHeight);
            futureSide = topSideHeight > bottomSideHeight ? "top" : "bottom";
        }

        setMaxHeight(() => `${futureMaxHeight}px`);
        setSide(() => futureSide);
    }, [isOpened]);
    const { onInteractOutside, onPointerDownOutside } = useHandleInteractOutside({ pointerDownOutside: () => setIsOpened(false) }, [setIsOpened]);

    useEffect(() => {
        checkSize();

        let timeout: NodeJS.Timeout;
        const handler = () => {
            clearTimeout(timeout);
            timeout = setTimeout(() => {
                checkSize();
                clearTimeout(timeout);
            }, 100);
        };

        window.addEventListener("resize", handler);
        window.addEventListener("scroll", handler);

        return () => {
            window.removeEventListener("resize", handler);
            window.removeEventListener("scroll", handler);
        };
    }, [isOpened]);

    return (
        <Popover.Root modal={false} open={isOpened} onOpenChange={setIsOpened}>
            <Popover.Trigger asChild>
                <UserAvatar.ListItem ref={triggerRef}>{t("common.avatarActions.View activities")}</UserAvatar.ListItem>
            </Popover.Trigger>
            <Popover.Content
                className="z-[999999] w-screen sm:max-w-screen-xs md:max-w-screen-sm lg:max-w-screen-md"
                side={side}
                onInteractOutside={onInteractOutside}
                onPointerDownOutside={onPointerDownOutside}
                {...getAvatarHoverCardAttrs()}
            >
                <SuspenseComponent shouldWrapChildren={false}>
                    <ActivityList
                        form={activityForm as any}
                        currentUser={currentUser}
                        outerClassName="max-h-[calc(var(--max-height)_-_theme(spacing.8))] px-4 pb-2.5 w-full"
                        outerStyle={style as React.CSSProperties}
                        viewType={currentUser.uid === userOrBot.uid ? "user" : "default"}
                    />
                </SuspenseComponent>
            </Popover.Content>
        </Popover.Root>
    );
}

export default UserAvatarDefaultViewActivitiesAction;
