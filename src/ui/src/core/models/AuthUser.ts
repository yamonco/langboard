import useUserApiKeyRolesUpdatedHandlers from "@/controllers/socket/user/useUserApiKeyRolesUpdatedHandlers";
import useUserDeactivatedHandlers from "@/controllers/socket/user/useUserDeactivatedHandlers";
import useUserDeletedHandlers from "@/controllers/socket/user/useUserDeletedHandlers";
import useUserMcpRolesUpdatedHandlers from "@/controllers/socket/user/useUserMcpRolesUpdatedHandlers";
import useUserNotificationDeletedHandlers from "@/controllers/socket/user/useUserNotificationDeletedHandlers";
import useUserProjectRolesUpdatedHandlers from "@/controllers/socket/user/useUserProjectRolesUpdatedHandlers";
import useUserSettingRolesUpdatedHandlers from "@/controllers/socket/user/useUserSettingRolesUpdatedHandlers";
import { ENotificationChannel, ENotificationScope, TNotificationType } from "@/core/models/types/notification.type";
import * as User from "@/core/models/User";
import * as UserGroup from "@/core/models/UserGroup";
import { unsubscribeModelSocketTopic } from "@/core/models/base/socketSubscriptions";
import { ESocketTopic } from "@langboard/core/enums";

interface INotificationUnsubscriptionMap {
    [ENotificationScope.All]?: {
        [T in TNotificationType]?: {
            [C in ENotificationChannel]?: bool;
        };
    };
    [ENotificationScope.Specific]?: {
        [K in TNotificationType]?: {
            [C in ENotificationChannel]?: string[];
        };
    };
}

export interface Interface extends User.Interface {
    user_groups: UserGroup.Interface[];
    subemails: { email: string; verified_at: string }[];
    preferred_lang: string;
    notification_unsubs: INotificationUnsubscriptionMap;
}

class AuthUser extends User.Model<Interface> {
    public static override get FOREIGN_MODELS() {
        return {
            user_groups: UserGroup.Model.MODEL_NAME,
        };
    }
    override get FOREIGN_MODELS() {
        return AuthUser.FOREIGN_MODELS;
    }

    public static get currentUser() {
        return AuthUser.getModel(() => true)!;
    }

    constructor(model: Record<string, unknown>) {
        super(model);

        this.subscribeSocketEvents(
            [
                useUserNotificationDeletedHandlers,
                useUserApiKeyRolesUpdatedHandlers,
                useUserSettingRolesUpdatedHandlers,
                useUserMcpRolesUpdatedHandlers,
                useUserProjectRolesUpdatedHandlers,
                useUserDeactivatedHandlers,
                useUserDeletedHandlers,
            ],
            {
                currentUser: this,
                user: this,
                isPrivate: true,
            }
        );

        AuthUser.subscribe("DELETION", this.uid, () => {
            unsubscribeModelSocketTopic(ESocketTopic.UserPrivate, [this.uid]);
        });
    }

    public get user_groups(): UserGroup.TModel[] {
        return this.getForeignValue("user_groups");
    }
    public set user_groups(value: (UserGroup.TModel | UserGroup.Interface)[]) {
        this.update({ user_groups: value });
    }

    public get subemails() {
        return this.getValue("subemails");
    }
    public set subemails(value) {
        this.update({ subemails: value });
    }

    public get preferred_lang() {
        return this.getValue("preferred_lang");
    }
    public set preferred_lang(value) {
        this.update({ preferred_lang: value });
    }

    public get notification_unsubs() {
        return this.getValue("notification_unsubs");
    }
    public set notification_unsubs(value) {
        this.update({ notification_unsubs: value });
    }
}

export const Model = AuthUser;
export type TModel = AuthUser;
