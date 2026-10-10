import useHoverEffect from "@/core/hooks/useHoverEffect";
import { TUserLikeModel } from "@/core/models/ModelRegistry";
import { createContext, useContext, useState } from "react";

export interface IUserAvatarContext {
    userOrBot: TUserLikeModel;
    hoverProps?: Record<string, string>;
    isOpened: bool;
    setIsOpened: React.Dispatch<React.SetStateAction<bool>>;
    setIsHoverLocked: React.Dispatch<React.SetStateAction<bool>>;
    onPointerEnter: () => void;
    onPointerLeave: () => void;
    getAvatarHoverCardAttrs: () => Record<string, string>;
}

interface IUserAvatarProps {
    userOrBot: TUserLikeModel;
    hoverProps?: Record<string, string>;
    children: React.ReactNode;
}

const initialContext = {
    userOrBot: {} as TUserLikeModel,
    isOpened: false,
    setIsOpened: () => {},
    setIsHoverLocked: () => {},
    onPointerEnter: () => {},
    onPointerLeave: () => {},
    getAvatarHoverCardAttrs: () => ({}),
};

const UserAvatarContext = createContext<IUserAvatarContext>(initialContext);

export const HOVER_DELAY = 500;
export const HOVER_USER_UID_ATTR = "data-avatar-user";
export const UserAvatarProvider = ({ userOrBot, hoverProps, children }: IUserAvatarProps): React.ReactNode => {
    const [isOpened, setIsOpened] = useState(false);
    const [isHoverLocked, setIsHoverLocked] = useState(false);
    const { onPointerEnter, onPointerLeave } = useHoverEffect({
        isOpened: isOpened && !isHoverLocked,
        setIsOpened,
        scopeAttr: HOVER_USER_UID_ATTR,
        expectedScopeValue: userOrBot.uid,
        delay: HOVER_DELAY,
    });
    const getAvatarHoverCardAttrs = (): Record<string, string> => {
        return {
            [HOVER_USER_UID_ATTR]: userOrBot.uid,
        };
    };

    return (
        <UserAvatarContext.Provider
            value={{
                userOrBot,
                hoverProps,
                isOpened,
                setIsOpened,
                setIsHoverLocked,
                onPointerEnter,
                onPointerLeave,
                getAvatarHoverCardAttrs,
            }}
        >
            {children}
        </UserAvatarContext.Provider>
    );
};

export const useUserAvatar = () => {
    const context = useContext(UserAvatarContext);
    if (!context) {
        throw new Error("useUserAvatar must be used within an UserAvatarProvider");
    }
    return context;
};
