/* eslint-disable @typescript-eslint/no-explicit-any */
import BaseModel, { BigIntColumn, TBigIntString } from "@/core/db/BaseModel";
import { Utils } from "@langboard/core/utils";
import User from "@/models/User";
import UserNotification, { ENotificationType } from "@/models/UserNotification";
import { Entity, Column, DeepPartial } from "typeorm";

export enum ENotificationChannel {
    Web = "web",
    Email = "email",
    Mobile = "mobile",
    IoT = "iot",
}

export enum ENotificationScope {
    All = "all",
    Specific = "specific",
}

export type TNotificationPublishData = {
    notification: Omit<DeepPartial<UserNotification>, "id">;
    api_notification: Record<string, any>;
    target_user: DeepPartial<User>;
    scope_models?: [string, number][];

    email_template_name?: string;
    email_formats?: Record<string, string>;
    source_notification_persisted?: boolean;
    web_notification_visible?: boolean;
};

@Entity({ name: "user_notification_unsubscription" })
class UserNotificationUnsubscription extends BaseModel {
    @BigIntColumn(false)
    public user_id!: TBigIntString;

    @Column({ type: "varchar", enum: ENotificationChannel, nullable: false })
    public channel!: ENotificationChannel;

    @Column({ type: "varchar", enum: ENotificationType, nullable: false })
    public notification_type!: ENotificationType;

    @Column({ type: "varchar", enum: ENotificationScope, nullable: false })
    public scope_type!: ENotificationScope;

    @Column({ type: "varchar", nullable: true })
    public specific_table: string | null = null;

    @BigIntColumn(false)
    public specific_id: TBigIntString | null = null;

    public static async hasUnsubscription(publishModel: TNotificationPublishData, channel: ENotificationChannel) {
        if (!publishModel.notification?.receiver_id || !publishModel.notification?.notification_type) {
            return false;
        }

        const unsubscription = await UserNotificationUnsubscription.findOne({
            where: {
                user_id: publishModel.notification.receiver_id.toString(),
                channel,
                notification_type: publishModel.notification.notification_type as ENotificationType,
            },
        });

        if (unsubscription) {
            return true;
        }

        if (!Utils.Type.isArray(publishModel.scope_models)) {
            return false;
        }

        const combinedTableIds: Record<string, Set<number>> = {};
        for (let i = 0; i < publishModel.scope_models.length; ++i) {
            const [tableName, recordId] = publishModel.scope_models[i];
            if (!combinedTableIds[tableName]) {
                combinedTableIds[tableName] = new Set();
            }
            combinedTableIds[tableName].add(recordId);
        }

        for (let i = 0; i < publishModel.scope_models.length; ++i) {
            const [tableName, recordId] = publishModel.scope_models[i];
            if (!combinedTableIds[tableName] || !combinedTableIds[tableName].has(recordId)) {
                continue;
            }

            const specificUnsubscription = await UserNotificationUnsubscription.findOne({
                where: {
                    user_id: publishModel.notification.receiver_id.toString(),
                    channel,
                    notification_type: publishModel.notification.notification_type as ENotificationType,
                    scope_type: ENotificationScope.Specific,
                    specific_table: tableName,
                    specific_id: recordId.toString(),
                },
            });

            if (specificUnsubscription) {
                return true;
            }
        }

        return false;
    }
}

export default UserNotificationUnsubscription;
