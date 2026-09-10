/* eslint-disable @typescript-eslint/no-explicit-any */
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Card from "@/components/base/Card";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Label from "@/components/base/Label";
import Loading from "@/components/base/Loading";
import Popover from "@/components/base/Popover";
import ScrollArea from "@/components/base/ScrollArea";
import Select from "@/components/base/Select";
import Switch from "@/components/base/Switch";
import Toast from "@/components/base/Toast";
import Tooltip from "@/components/base/Tooltip";
import DateDistance from "@/components/DateDistance";
import InfiniteScroller from "@/components/InfiniteScroller";
import UserAvatar from "@/components/UserAvatar";
import UserAvatarDefaultList from "@/components/UserAvatarDefaultList";
import { QUERY_NAMES } from "@/constants";
import useGetNotificationList from "@/controllers/api/notification/useGetNotificationList";
import useDeleteAllUserNotificationsHandlers from "@/controllers/socket/notification/useDeleteAllUserNotificationsHandlers";
import useDeleteUserNotificationHandlers from "@/controllers/socket/notification/useDeleteUserNotificationHandlers";
import useReadAllUserNotificationsHandlers from "@/controllers/socket/notification/useReadAllUserNotificationsHandlers";
import useReadUserNotificationHandlers from "@/controllers/socket/notification/useReadUserNotificationHandlers";
import useUserNotifiedHandlers from "@/controllers/socket/user/useUserNotifiedHandlers";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { AuthUser, User, UserNotification } from "@/core/models";
import { TUserLikeModel } from "@/core/models/ModelRegistry";
import { ENotificationType } from "@/core/models/types/notification.type";
import { useSocket } from "@/core/providers/SocketProvider";
import { ROUTES } from "@/core/routing/constants";
import { getUserSettingsStore, IUserSettings, NOTIFICATIONS_TIME_RANGE_OPTIONS, useUserSettings } from "@/core/stores/UserSettingsStore";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { memo, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

interface IHeaderUserNotificationProps {
    currentUser: AuthUser.TModel;
}

const NOTIFICATION_PAGE_SIZE = 20;

const HeaderUserNotification = memo(({ currentUser }: IHeaderUserNotificationProps) => {
    const [t] = useTranslation();
    const socket = useSocket();
    const [updated, forceUpdate] = useReducer((x) => x + 1, 0);
    const unreadNotifications = UserNotification.Model.useModels((model) => !model.read_at, [updated]);
    const [isOnlyUnread, setIsOnlyUnread] = useState(true);
    const [isOpened, setIsOpened] = useState(false);
    const [hasMore, setHasMore] = useState(false);
    const [unreadCount, setUnreadCount] = useState(0);
    const { mutateAsync } = useGetNotificationList();
    const timeRange = useUserSettings("notifications_time_range");
    const { send: sendReadAllUserNotifications } = useReadAllUserNotificationsHandlers();
    const { send: sendDeleteAllUserNotifications } = useDeleteAllUserNotificationsHandlers();
    const notifiedHandlers = useMemo(
        () =>
            useUserNotifiedHandlers({
                currentUser,
                callback: () => {
                    setUnreadCount((prev) => prev + 1);
                    if (isOpened) {
                        return;
                    }

                    Toast.Add.info(t("notification.You have a new notification."));
                },
            }),
        [currentUser, isOpened]
    );
    useSwitchSocketHandlers({ socket, handlers: notifiedHandlers });
    const readAllNotifications = useCallback(() => {
        sendReadAllUserNotifications({});
        setUnreadCount(0);
        for (let i = 0; i < unreadNotifications.length; ++i) {
            const notification = unreadNotifications[i];
            notification.read_at = new Date();
        }
    }, [unreadNotifications]);
    const deleteAllNotifications = useCallback(() => {
        sendDeleteAllUserNotifications({});
        UserNotification.Model.deleteModels(() => true);
        setHasMore(false);
        setUnreadCount(0);
    }, []);
    const closeNotifications = useCallback(() => setIsOpened(false), []);
    const updateTimeRange = (value: IUserSettings["notifications_time_range"]) => {
        getUserSettingsStore().updateSettingsByKey("notifications_time_range", value);
    };

    useEffect(() => {
        UserNotification.Model.deleteModels(() => true);
        mutateAsync({
            time_range: timeRange || "3d",
            page: 1,
            limit: NOTIFICATION_PAGE_SIZE,
        }).then((res) => {
            setHasMore(!!res.has_more);
            setUnreadCount(res.unread_count || 0);
            forceUpdate();
        });
    }, [timeRange]);

    const loadMoreNotifications = useCallback(
        async (page: number) => {
            const res = await mutateAsync({
                time_range: timeRange || "3d",
                page,
                limit: NOTIFICATION_PAGE_SIZE,
            });
            setHasMore(!!res.has_more);
            setUnreadCount(res.unread_count || 0);
            forceUpdate();
            return true;
        },
        [timeRange, mutateAsync]
    );

    return (
        <Popover.Root modal open={isOpened} onOpenChange={setIsOpened}>
            <Popover.Trigger asChild>
                <Button
                    variant="ghost"
                    className="relative p-2"
                    title={t(unreadCount > 0 ? "notification.{count} notifications received" : "notification.Notifications", {
                        count: unreadCount,
                    })}
                >
                    <IconComponent icon="bell" />
                    {unreadCount > 0 && (
                        <Box
                            position="absolute"
                            top="0"
                            right={unreadCount > 99 ? "-1.5" : unreadCount > 9 ? "0.5" : "1.5"}
                            px="0.5"
                            rounded="sm"
                            textSize="xs"
                            className="bg-destructive text-destructive-foreground"
                        >
                            {unreadCount > 99 ? "99+" : unreadCount}
                        </Box>
                    )}
                </Button>
            </Popover.Trigger>
            <Popover.Content className="min-w-[min(theme(screens.xs),100vw)] max-w-[min(theme(screens.xs),100vw)] p-0">
                <Flex items="center" justify="between" py="2.5" px="3" className="border-b">
                    <Flex items="center" gap="1.5" textSize="base" weight="semibold">
                        {t("notification.Notifications")}
                        <Select.Root value={timeRange || "3d"} onValueChange={updateTimeRange as any}>
                            <Select.Trigger className="h-8 gap-1 px-1.5 py-0.5 text-xs">
                                <Select.Value />
                            </Select.Trigger>
                            <Select.Content
                                onPointerDown={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                }}
                            >
                                {NOTIFICATIONS_TIME_RANGE_OPTIONS.map((option) => (
                                    <Select.Item key={`notification-time-range-${option}`} value={option}>
                                        {t(`notification.timeRanges.${option}`)}
                                    </Select.Item>
                                ))}
                            </Select.Content>
                        </Select.Root>
                    </Flex>
                    <Flex gap="1.5" items="center">
                        <Label display="inline-flex" cursor="pointer" items="center" gap="2" textSize="xs">
                            <Switch checked={isOnlyUnread} onCheckedChange={setIsOnlyUnread} />
                            <Box as="span">{t("notification.Only show unread")}</Box>
                        </Label>
                        {unreadCount > 0 && (
                            <Button
                                variant="ghost"
                                size="icon-sm"
                                title={t("notification.Read all notifications")}
                                titleAlign="end"
                                titleSide="bottom"
                                onClick={readAllNotifications}
                            >
                                <IconComponent icon="check-check" size="4" />
                            </Button>
                        )}
                        <Button
                            variant="destructive-ghost"
                            size="icon-sm"
                            title={t("notification.Delete all notifications")}
                            titleAlign="end"
                            titleSide="bottom"
                            onClick={deleteAllNotifications}
                        >
                            <IconComponent icon="trash-2" size="4" />
                        </Button>
                    </Flex>
                </Flex>
                <HeaderUserNotificationList
                    hasMore={hasMore}
                    isOnlyUnread={isOnlyUnread}
                    loadMore={loadMoreNotifications}
                    onNavigate={closeNotifications}
                    setUnreadCount={setUnreadCount}
                    timeRange={timeRange || "3d"}
                    updater={[updated, forceUpdate]}
                />
            </Popover.Content>
        </Popover.Root>
    );
});

interface IHeaderUserNotificationListProps {
    hasMore: bool;
    isOnlyUnread: bool;
    loadMore: (page: number) => Promise<bool>;
    onNavigate: () => void;
    setUnreadCount: React.Dispatch<React.SetStateAction<number>>;
    timeRange: IUserSettings["notifications_time_range"];
    updater: [number, React.DispatchWithoutAction];
}

function HeaderUserNotificationList({
    hasMore,
    isOnlyUnread,
    loadMore,
    onNavigate,
    setUnreadCount,
    timeRange,
    updater,
}: IHeaderUserNotificationListProps) {
    const [t] = useTranslation();
    const [updated] = updater;
    const flatNotifications = UserNotification.Model.useModels(() => true, [updated]);
    const filteredNotifications = useMemo(
        () =>
            flatNotifications
                .filter((notification) => (isOnlyUnread ? !notification.read_at : true))
                .sort((a, b) => b.created_at.getTime() - a.created_at.getTime()),
        [flatNotifications, isOnlyUnread]
    );
    const viewportRef = useRef<HTMLDivElement | null>(null);

    return (
        <ScrollArea.Root
            viewportRef={viewportRef}
            mutable={`${updated}:${filteredNotifications.length}:${hasMore}`}
            className="h-[min(theme(spacing.96),calc(100vh_-_theme(spacing.16)_-_theme(spacing.14)))]"
        >
            {!filteredNotifications.length && !hasMore && (
                <Flex items="center" justify="center" maxH="80" minH="80">
                    {t("notification.No notifications received.")}
                </Flex>
            )}
            <InfiniteScroller.Default
                key={`${timeRange}-${isOnlyUnread ? "unread" : "all"}`}
                scrollable={() => viewportRef.current}
                initialLoad={false}
                loadMore={loadMore}
                hasMore={hasMore}
                totalCount={filteredNotifications.length + (hasMore ? 1 : 0)}
                loader={
                    <Flex justify="center" py="6" key={Utils.String.Token.shortUUID()}>
                        <Loading variant="secondary" size={{ initial: "2", sm: "3" }} />
                    </Flex>
                }
                className="w-full p-2"
                rowClassName="w-full"
            >
                {filteredNotifications.map((notification) => (
                    <HeaderUserNotificationItem
                        key={notification.uid}
                        notification={notification}
                        onNavigate={onNavigate}
                        setUnreadCount={setUnreadCount}
                        updater={updater}
                    />
                ))}
            </InfiniteScroller.Default>
        </ScrollArea.Root>
    );
}

interface IHeaderUserNotificationItemProps {
    notification: UserNotification.TModel;
    onNavigate: () => void;
    setUnreadCount: React.Dispatch<React.SetStateAction<number>>;
    updater: [number, React.DispatchWithoutAction];
}

const HeaderUserNotificationItem = memo(({ notification, onNavigate, setUnreadCount, updater }: IHeaderUserNotificationItemProps) => {
    const [_, forceUpdate] = updater;
    const [t, i18n] = useTranslation();
    const navigate = usePageNavigateRef();
    const { send: sendReadUserNotification } = useReadUserNotificationHandlers();
    const { send: sendDeleteUserNotification } = useDeleteUserNotificationHandlers();
    const readAt = notification.useField("read_at");
    const readNotification = (shouldUpdate: bool) => {
        const wasUnread = !notification.read_at;
        sendReadUserNotification({ uid: notification.uid });
        notification.read_at = new Date();
        if (wasUnread) {
            setUnreadCount((prev) => Math.max(prev - 1, 0));
        }
        if (shouldUpdate) {
            forceUpdate();
        }
    };
    const deleteNotification = () => {
        if (!notification.read_at) {
            setUnreadCount((prev) => Math.max(prev - 1, 0));
        }
        sendDeleteUserNotification({ uid: notification.uid });
        UserNotification.Model.deleteModel(notification.uid);
    };

    const UserAvatarComp = ({ userOrBot }: { userOrBot?: TUserLikeModel }) => {
        if (!userOrBot) {
            return <></>;
        }

        return (
            <UserAvatar.Root
                userOrBot={userOrBot}
                avatarSize="xs"
                withNameProps={{
                    className: "inline-flex gap-1 cursor-pointer select-none",
                    nameClassName: "text-base",
                }}
            >
                <UserAvatarDefaultList userOrBot={userOrBot} scope={{ projectUID: notification.records.project?.uid }} />
            </UserAvatar.Root>
        );
    };

    const movePage = () => {
        const route = getRoute(notification);
        readNotification(false);
        onNavigate();
        navigate(route);
    };
    const messageVars = getNotificationMessageVars(notification);
    const ruleTranslationKey = getNotificationScheduleRuleTranslationKey(notification, messageVars);
    const titleI18nKey =
        ruleTranslationKey && i18n.exists(`notification.ruleTitles.${ruleTranslationKey}`)
            ? `notification.ruleTitles.${ruleTranslationKey}`
            : `notification.titles.${notification.type}`;
    const subtitleI18nKey =
        ruleTranslationKey && i18n.exists(`notification.ruleSubtitles.${ruleTranslationKey}`)
            ? `notification.ruleSubtitles.${ruleTranslationKey}`
            : `notification.subtitles.${notification.type}`;
    return (
        <Card.Root>
            <Card.Header className="p-3">
                <Flex items="center" gap="1" justify="between">
                    <Box
                        as="span"
                        display="inline-flex"
                        weight="semibold"
                        gap="1"
                        cursor="pointer"
                        className={cn("truncate text-primary hover:opacity-80", !!readAt && "opacity-50")}
                        onClick={movePage}
                    >
                        <Trans
                            i18nKey={titleI18nKey}
                            values={{ records: notification.records, message_vars: messageVars }}
                            components={{
                                Who: <UserAvatarComp userOrBot={notification.notifier_user ?? notification.notifier_bot} />,
                                Span: <Box as="span" className="truncate" />,
                            }}
                        />
                    </Box>
                    <Flex items="center" gap="1">
                        {!readAt && (
                            <Button
                                variant="ghost"
                                size="icon-sm"
                                title={t("notification.Read notification")}
                                titleAlign="end"
                                titleSide="bottom"
                                className="size-7"
                                onClick={() => readNotification(true)}
                            >
                                <IconComponent icon="check" size="3" />
                            </Button>
                        )}
                        <Button
                            variant="destructive-ghost"
                            size="icon-sm"
                            title={t("notification.Delete notification")}
                            titleAlign="end"
                            titleSide="bottom"
                            className="size-7"
                            onClick={deleteNotification}
                        >
                            <IconComponent icon="trash-2" size="3" />
                        </Button>
                    </Flex>
                </Flex>
                <Card.Description className={cn("truncate text-xs", !!readAt && "opacity-50")}>
                    {t(subtitleI18nKey, { records: notification.records, message_vars: messageVars })}
                </Card.Description>
            </Card.Header>
            <HeaderUserNotificationItemContent notification={notification} className={readAt ? "opacity-50" : ""} />
            <Card.Footer className={cn("justify-end px-3 pb-4", !!readAt && "opacity-50")}>
                <Card.Description className="text-xs">
                    <DateDistance date={notification.created_at} />
                </Card.Description>
            </Card.Footer>
        </Card.Root>
    );
});

const getNotificationScheduleRuleTranslationKey = (notification: UserNotification.TModel, messageVars: Record<string, unknown>) => {
    if (notification.type !== ENotificationType.ScheduledRule) {
        return null;
    }

    const { target, field, operator } = notification.message_vars;
    if (!Utils.Type.isString(target) || !Utils.Type.isString(field) || !Utils.Type.isString(operator)) {
        return null;
    }

    const resolvedOperator = field === "deadline_at" && Utils.Type.isString(messageVars.deadline_state) ? messageVars.deadline_state : operator;

    return `${target}.${field}.${resolvedOperator}`;
};

const getNotificationMessageVars = (notification: UserNotification.TModel) => {
    const messageVars = notification.message_vars;
    if (notification.type !== ENotificationType.ScheduledRule) {
        return messageVars;
    }

    const { target, field, operator } = messageVars;
    if (!Utils.Type.isString(target) || !Utils.Type.isString(field) || !Utils.Type.isString(operator)) {
        return messageVars;
    }

    if (field === "deadline_at" && Utils.Type.isString(messageVars.deadline_at)) {
        const deadlineDate = new Date(messageVars.deadline_at);
        if (Number.isNaN(deadlineDate.getTime())) {
            return messageVars;
        }

        const isOverdue = deadlineDate.getTime() < Date.now();
        return {
            ...messageVars,
            deadline_state: isOverdue ? "overdue" : "within_next_days",
            days_delta: getCalendarDaysDelta(deadlineDate, new Date()),
        };
    }

    if (operator === "older_than_days") {
        const fieldDateValue = messageVars[field];
        if (!Utils.Type.isString(fieldDateValue)) {
            return {
                ...messageVars,
                days_delta: messageVars.value,
            };
        }

        const fieldDate = new Date(fieldDateValue);
        if (Number.isNaN(fieldDate.getTime())) {
            return {
                ...messageVars,
                days_delta: messageVars.value,
            };
        }

        return {
            ...messageVars,
            days_delta: getCalendarDaysDelta(fieldDate, new Date()),
        };
    }

    return messageVars;
};

const getCalendarDaysDelta = (targetDate: Date, baseDate: Date) => {
    const targetDateOnly = new Date(targetDate.getFullYear(), targetDate.getMonth(), targetDate.getDate());
    const baseDateOnly = new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate());

    return Math.abs(Math.round((targetDateOnly.getTime() - baseDateOnly.getTime()) / 86400000));
};

function HeaderUserNotificationItemContent({ notification, className }: { notification: UserNotification.TModel; className?: string }) {
    let content = null;
    switch (notification.type) {
        case ENotificationType.MentionedInCard:
        case ENotificationType.MentionedInComment:
        case ENotificationType.MentionedInWiki:
        case ENotificationType.ReactedToComment:
            if (Utils.Type.isString(notification.message_vars.line)) {
                content = <HeaderUserNotificationItemMentionedText content={notification.message_vars.line} />;
            }
            break;
        default:
            break;
    }

    if (!content) {
        return null;
    }

    return (
        <Card.Content className={cn("p-3 pt-0", className)}>
            <Flex items="center" textSize="sm" className="truncate rounded-md bg-muted px-3 py-2">
                {content}
            </Flex>
        </Card.Content>
    );
}

function HeaderUserNotificationItemMentionedText({ content }: { content: string }) {
    const mentionPattern = /\[\*\*@([\w-]+)\*\*\]\(([\w]+)\)/g;
    const [elements, title] = useMemo(() => {
        const newElements = [];
        let lastIndex = 0;
        let match: RegExpExecArray | null;
        let newTitle: string = "";
        while ((match = mentionPattern.exec(content)) !== null) {
            const [fullMatch, username, userUID] = match;
            const targetUser = User.Model.getModel(userUID);
            const userName = targetUser ? `${targetUser.firstname} ${targetUser.lastname}` : username;
            const matchIndex = match.index;

            if (matchIndex > lastIndex) {
                const textSegment = content.slice(lastIndex, matchIndex);
                newElements.push(
                    <Box as="span" key={`text-${lastIndex}`}>
                        {textSegment}
                    </Box>
                );
                newTitle = `${newTitle}${textSegment}`;
            }

            newElements.push(
                <Box
                    as="span"
                    key={`mention-${matchIndex}`}
                    className="cursor-default select-none rounded-full bg-primary/70 px-2 py-1 text-primary-foreground"
                >
                    @{userName}
                </Box>
            );
            newTitle = `${newTitle}@${userName}`;

            lastIndex = matchIndex + fullMatch.length;
        }

        if (lastIndex < content.length) {
            const textSegment = content.slice(lastIndex);
            newElements.push(
                <Box as="span" key={`text-${lastIndex}`}>
                    {textSegment}
                </Box>
            );
            newTitle = `${newTitle}${textSegment}`;
        }

        return [newElements, newTitle];
    }, [content]);

    return (
        <Tooltip.Root>
            <Tooltip.Trigger asChild>
                <Box as="span" className="truncate">
                    {elements}
                </Box>
            </Tooltip.Trigger>
            <Tooltip.Content>{title}</Tooltip.Content>
        </Tooltip.Root>
    );
}

const getRoute = (notification: UserNotification.TModel) => {
    switch (notification.type) {
        case ENotificationType.ProjectInvited:
            return `${ROUTES.BOARD.INVITATION}?${QUERY_NAMES.PROJCT_INVITATION_TOKEN}=${notification.records.project_invitation.encrypted_token}`;
        case ENotificationType.MentionedInCard:
            return ROUTES.BOARD.CARD(notification.records.project.uid, notification.records.card.uid);
        case ENotificationType.MentionedInComment:
            return ROUTES.BOARD.CARD(notification.records.project.uid, notification.records.card.uid);
        case ENotificationType.MentionedInWiki:
            return ROUTES.BOARD.WIKI_PAGE(notification.records.project.uid, notification.records.project_wiki.uid);
        case ENotificationType.ReactedToComment:
            return ROUTES.BOARD.CARD(notification.records.project.uid, notification.records.card.uid);
        case ENotificationType.AssignedToCard:
            return ROUTES.BOARD.CARD(notification.records.project.uid, notification.records.card.uid);
        case ENotificationType.NotifiedFromChecklist:
            return ROUTES.BOARD.CARD(notification.records.project.uid, notification.records.card.uid);
        case ENotificationType.ScheduledRule:
            if (notification.records.card) {
                return ROUTES.BOARD.CARD(notification.records.project.uid, notification.records.card.uid);
            }
            return ROUTES.BOARD.MAIN(notification.records.project.uid);
        default:
            throw new Error("Invalid notification type.");
    }
};

export default HeaderUserNotification;
