/* eslint-disable @/max-len */
import { memo } from "react";
import Avatar from "@/components/base/Avatar";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import { BotModel, User } from "@/core/models";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { useTranslation } from "react-i18next";
import { tv } from "tailwind-variants";
import { useUserAvatar } from "@/components/UserAvatar/Provider";
import { IUserAvatarProps } from "@/components/UserAvatar/types";
import UserLikeComponent from "@/components/UserLikeComponent";

export const TriggerVariants = tv(
    {
        base: "relative after:transition-all after:block after:z-[-1] after:size-full after:absolute after:top-0 after:left-0 after:rounded-full after:bg-background after:opacity-0",
        variants: {
            hoverable: {
                true: "hover:after:z-10 hover:after:bg-accent hover:after:opacity-45 cursor-pointer",
            },
        },
    },
    {
        responsiveVariants: true,
    }
);

interface IBaseTriggerProps extends Omit<IUserAvatarProps, "listAlign" | "customTrigger"> {}

const UserAvatarTrigger = memo(({ userOrBot, ...props }: IBaseTriggerProps) => {
    return <UserLikeComponent userOrBot={userOrBot} userComp={UserTrigger} botComp={BotTrigger} props={props} />;
});

function UserTrigger({ user, children, ...props }: Omit<IBaseTriggerProps, "userOrBot"> & { user: User.TModel }) {
    const [t] = useTranslation();
    const userType = user.useField("type");
    const firstname = user.useField("firstname");
    const lastname = user.useField("lastname");
    const avatarUrl = user.useField("avatar");
    const membership = user.useField("membership_classification");
    const initials = Utils.String.getInitials(firstname, lastname);
    const isDeletedUser = user.isDeletedUser(userType);
    const isPresentableUnknownUser = user.isPresentableUnknownUser(userType);

    let names: string;
    if (isDeletedUser) {
        names = t("common.Unknown User");
    } else if (isPresentableUnknownUser) {
        names = firstname;
    } else {
        names = `${firstname} ${lastname}`;
    }

    return (
        <Trigger
            {...props}
            membership={membership}
            initials={initials}
            avatarUrl={avatarUrl}
            avatarFallback={isPresentableUnknownUser || isDeletedUser ? <IconComponent icon="user" className="size-[80%]" /> : initials}
            hoverable={!!children && !isDeletedUser}
            names={names}
            children={children}
        />
    );
}

function BotTrigger({ bot, children, ...props }: Omit<IBaseTriggerProps, "userOrBot"> & { bot: BotModel.TModel }) {
    const botName = bot.useField("name");
    const avatarUrl = bot.useField("avatar");
    const initials = Utils.String.getInitials(botName);

    return (
        <Trigger
            {...props}
            initials={initials}
            avatarUrl={avatarUrl}
            avatarFallback={<IconComponent icon="bot" className="size-[80%]" />}
            hoverable={!!children}
            names={botName}
            children={children}
        />
    );
}

interface ITriggerProps extends Omit<IBaseTriggerProps, "userOrBot"> {
    membership?: "internal" | "external" | "unknown";
    initials: string;
    avatarUrl?: string;
    avatarFallback: React.ReactNode;
    hoverable: bool;
    names: string;
}

function Trigger({
    avatarSize,
    membership,
    withNameProps,
    className,
    initials,
    avatarUrl,
    avatarFallback,
    names,
    hoverable,
    children,
}: ITriggerProps): React.ReactNode {
    const { isOpened, setIsOpened } = useUserAvatar();
    const [t] = useTranslation();

    const [bgColor, textColor] = new Utils.Color.Generator(initials).generateAvatarColor();

    const styles: Record<string, string> = {
        "--avatar-bg": bgColor,
        "--avatar-text-color": textColor,
    };

    let avatarRootClassName = className;
    let avatarRootOnClick;

    if (children) {
        avatarRootClassName = cn(avatarRootClassName, TriggerVariants({ hoverable }));
        avatarRootOnClick = () => setIsOpened(!isOpened);
    }

    const avatar = (
        <Avatar.Root size={avatarSize} className={cn(avatarRootClassName, "relative overflow-visible")} onClick={avatarRootOnClick}>
            <Avatar.Image src={avatarUrl} className="rounded-full" />
            <Avatar.Fallback className="bg-[--avatar-bg] font-semibold text-[--avatar-text-color]" style={styles}>
                {avatarFallback}
            </Avatar.Fallback>
            {(membership === "internal" || membership === "external") && (
                <span
                    title={t(`user.${membership === "internal" ? "Internal member" : "External member"}`)}
                    aria-label={t(`user.${membership === "internal" ? "Internal member" : "External member"}`)}
                    data-member-classification={membership}
                    className={cn(
                        "pointer-events-none absolute -bottom-0.5 -right-0.5 z-20 flex size-3.5 items-center justify-center rounded-full border border-background bg-background",
                        membership === "internal" ? "text-primary" : "text-amber-500"
                    )}
                >
                    <IconComponent icon={membership === "internal" ? "building-2" : "globe"} className="size-2.5" />
                </span>
            )}
        </Avatar.Root>
    );

    let avatarWrapper = avatar;

    if (withNameProps) {
        withNameProps = {
            className: "gap-2",
            nameClassName: "text-sm font-semibold text-foreground",
            noAvatar: false,
            ...withNameProps,
        };
        avatarWrapper = (
            <Flex items="center" style={styles} className={withNameProps.className} onClick={avatarRootOnClick}>
                {!withNameProps.noAvatar && avatar}
                {withNameProps.customName ? withNameProps.customName : <span className={withNameProps.nameClassName}>{names}</span>}
            </Flex>
        );
    }

    return avatarWrapper;
}

export default UserAvatarTrigger;
