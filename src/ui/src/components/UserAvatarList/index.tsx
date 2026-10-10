import Avatar from "@/components/base/Avatar";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import HoverCard from "@/components/base/HoverCard";
import ScrollArea from "@/components/base/ScrollArea";
import Separator from "@/components/base/Separator";
import Skeleton from "@/components/base/Skeleton";
import { LabelBadge } from "@/components/LabelBadge";
import UserAvatar from "@/components/UserAvatar";
import { IUserAvatarProps } from "@/components/UserAvatar/types";
import UserAvatarDefaultList from "@/components/UserAvatarDefaultList";
import { IUserAvatarDefaultListProviderProps } from "@/components/UserAvatarDefaultList/Provider";
import { TUserLikeModel } from "@/core/models/ModelRegistry";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { forwardRef, Fragment, memo, useState } from "react";
import { useTranslation } from "react-i18next";
import { groupMembers } from "./memberGroups";

const SPACING_MAP = {
    1: "-space-x-5",
    2: "-space-x-4",
    3: "-space-x-3",
    4: "-space-x-2",
    5: "-space-x-1",
    none: "",
};

export interface ISkeletonUserAvatarListProps {
    count: number;
    size?: IUserAvatarProps["avatarSize"];
    spacing?: "1" | "2" | "3" | "4" | "5" | "none";
    className?: string;
}

export const SkeletonUserAvatarList = ({ count, size, spacing = "none", className = "" }: ISkeletonUserAvatarListProps) => {
    return (
        <Flex className={cn("rtl:space-x-reverse", SPACING_MAP[spacing])}>
            {Array.from({ length: count }).map(() => (
                <Skeleton key={Utils.String.Token.shortUUID()} display="inline-block" className={cn(Avatar.Variants({ size }), className)} />
            ))}
        </Flex>
    );
};

export interface IUserAvatarListProps extends Omit<React.ComponentProps<typeof Flex>, "size"> {
    userOrBots: TUserLikeModel[];
    maxVisible: number;
    size?: IUserAvatarProps["avatarSize"];
    spacing?: "1" | "2" | "3" | "4" | "5" | "none";
    listAlign?: IUserAvatarProps["listAlign"];
    scope?: IUserAvatarDefaultListProviderProps["scope"];
    avatarHoverProps?: IUserAvatarProps["hoverProps"];
    onlyList?: bool;
    renderAvatar?: (user: TUserLikeModel, avatar: React.ReactNode) => React.ReactNode;
    groupByMembership?: boolean;
    currentUserUID?: string;
}

export const UserAvatarList = memo(
    forwardRef<HTMLDivElement, IUserAvatarListProps>((props: IUserAvatarListProps, ref) => {
        const {
            maxVisible,
            className,
            userOrBots,
            size = "default",
            spacing = "2",
            listAlign,
            scope,
            avatarHoverProps,
            onlyList,
            renderAvatar,
            groupByMembership,
            currentUserUID,
            ...flexProps
        } = props;
        const [t] = useTranslation();
        const moreUsersCount = userOrBots.length - maxVisible;

        if (groupByMembership) {
            const labels = { personal: "Personal space", internal: "Internal member", external: "External member", unknown: "Unverified membership" };
            const groups = groupMembers(userOrBots, currentUserUID);
            return (
                <Flex ref={ref} items="center" wrap gap="2" className={className} {...flexProps}>
                    {groups.map(({ key, members }) => (
                        <div
                            key={key}
                            role="group"
                            aria-label={t(`user.${labels[key]}`)}
                            title={t(`user.${labels[key]}`)}
                            data-member-group={key}
                            className="rounded-lg border border-border/50 px-1 py-0.5"
                        >
                            <UserAvatarList {...props} userOrBots={members} groupByMembership={false} className="" />
                        </div>
                    ))}
                </Flex>
            );
        }

        return (
            <Flex position="relative" className={cn("rtl:space-x-reverse", SPACING_MAP[spacing], className)} ref={ref} {...flexProps}>
                {userOrBots.slice(0, maxVisible).map((userOrBot) => {
                    const avatar = (
                        <UserAvatar.Root
                            key={`user-avatar-${userOrBot.MODEL_NAME}-${userOrBot.uid}`}
                            userOrBot={userOrBot}
                            avatarSize={size}
                            listAlign={listAlign}
                            className="hover:z-50"
                            hoverProps={avatarHoverProps}
                            onlyAvatar={onlyList}
                        >
                            <UserAvatarDefaultList userOrBot={userOrBot} scope={scope} />
                        </UserAvatar.Root>
                    );
                    return (
                        <Fragment key={`avatar-${userOrBot.MODEL_NAME}-${userOrBot.uid}`}>
                            {renderAvatar ? renderAvatar(userOrBot, avatar) : avatar}
                        </Fragment>
                    );
                })}
                {moreUsersCount > 0 && <UserAvatarMoreList {...props} />}
            </Flex>
        );
    })
);

interface IUserAvatarMoreList extends IUserAvatarListProps {
    isBadge?: bool;
}

const UserAvatarMoreList = memo(
    ({ maxVisible, userOrBots, size = "default", listAlign, isBadge, scope, avatarHoverProps, renderAvatar }: IUserAvatarMoreList) => {
        const [isOpened, setIsOpened] = useState(false);
        const moreUsersCount = userOrBots.length - maxVisible;
        const moreUsersCountText = moreUsersCount > 99 ? "99" : moreUsersCount;

        return (
            <HoverCard.Root open={isOpened} onOpenChange={setIsOpened} {...avatarHoverProps}>
                <HoverCard.Trigger asChild>
                    {isBadge ? (
                        <Box cursor="pointer" onClick={() => setIsOpened(!isOpened)}>
                            <LabelBadge
                                name={`+${moreUsersCountText}`}
                                color="hsl(var(--secondary))"
                                textColor="hsl(var(--secondary-foreground))"
                                noTooltip
                            />
                        </Box>
                    ) : (
                        <Button
                            variant="secondary"
                            className={cn(Avatar.Variants({ size }), "z-10 m-0 border-none p-0")}
                            onClick={() => setIsOpened(!isOpened)}
                        >
                            +{moreUsersCountText}
                        </Button>
                    )}
                </HoverCard.Trigger>
                <HoverCard.Content className="z-50 w-auto p-0" align="end" {...avatarHoverProps}>
                    <ScrollArea.Root>
                        <Box maxH="52" minW="40" py="1">
                            {userOrBots.slice(maxVisible).map((userOrBot, i) => {
                                const avatar = (
                                    <UserAvatar.Root
                                        userOrBot={userOrBot}
                                        avatarSize="xs"
                                        listAlign={listAlign}
                                        withNameProps={{ className: "justify-start gap-2 px-3 py-1 hover:bg-accent/70 cursor-pointer" }}
                                        hoverProps={avatarHoverProps}
                                    >
                                        <UserAvatarDefaultList userOrBot={userOrBot} scope={scope} />
                                    </UserAvatar.Root>
                                );
                                return (
                                    <Fragment key={`user-avatar-${userOrBot.MODEL_NAME}-${userOrBot.uid}`}>
                                        {i !== 0 && <Separator className="my-1 h-px bg-muted" />}
                                        {renderAvatar ? renderAvatar(userOrBot, avatar) : avatar}
                                    </Fragment>
                                );
                            })}
                        </Box>
                    </ScrollArea.Root>
                </HoverCard.Content>
            </HoverCard.Root>
        );
    }
);
