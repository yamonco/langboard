import * as nodemailer from "nodemailer";
import * as fs from "fs";
import Consumer from "@/core/broadcast/Consumer";
import Subscription from "@/core/server/Subscription";
import UserNotification from "@/models/UserNotification";
import UserNotificationUnsubscription, { ENotificationChannel, TNotificationPublishData } from "@/models/UserNotificationUnsubscription";
import { MAIL_FROM, MAIL_FROM_NAME, MAIL_PASSWORD, MAIL_PORT, MAIL_SERVER, MAIL_SSL_TLS, MAIL_USERNAME, PROJECT_NAME, ROOT_DIR } from "@/Constants";
import * as path from "path";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic } from "@langboard/core/enums";
import SnowflakeID from "@/core/db/SnowflakeID";
import type { QueryDeepPartialEntity } from "typeorm/query-builder/QueryPartialEntity.js";

const convertBigIntToString = <T>(value: T): T => {
    if (Utils.Type.isBigInt(value)) {
        return value.toString() as T;
    }

    if (Utils.Type.isArray(value)) {
        return value.map((item) => convertBigIntToString(item)) as T;
    }

    if (value instanceof Date) {
        return value;
    }

    if (Utils.Type.isObject<Record<string, unknown>>(value)) {
        const convertedValue: Record<string, unknown> = {};

        Object.entries(value).forEach(([key, nestedValue]) => {
            convertedValue[key as unknown as string] = convertBigIntToString(nestedValue);
        });

        return convertedValue as T;
    }

    return value;
};

Consumer.register(
    "notification_publish",
    async (data: unknown) => {
        const webNotification = async (model: TNotificationPublishData) => {
            const hasUnsubscription = await UserNotificationUnsubscription.hasUnsubscription(model, ENotificationChannel.Web);

            if (hasUnsubscription || !model.api_notification?.notifier_user?.uid) {
                return;
            }

            const notification = model.notification;
            if (!notification.notifier_type || !notification.notifier_id || !notification.receiver_id || !notification.notification_type) {
                return;
            }

            const recordList = notification.record_list?.map(([record, id]) => [record, id.toString()] as [string, string]) ?? [];

            const notificationId = SnowflakeID.fromShortCode(model.api_notification.uid).toString();
            await UserNotification.createQueryBuilder()
                .insert()
                .into(UserNotification)
                .values({
                    id: notificationId,
                    notifier_type: notification.notifier_type,
                    notifier_id: notification.notifier_id.toString(),
                    receiver_id: notification.receiver_id.toString(),
                    notification_type: notification.notification_type,
                    message_vars: notification.message_vars as QueryDeepPartialEntity<UserNotification>["message_vars"],
                    record_list: recordList,
                    read_at: notification.read_at ?? null,
                    created_at: notification.created_at,
                    updated_at: notification.updated_at,
                })
                .orIgnore()
                .execute();

            if (!(await UserNotification.findOneBy({ id: notificationId }))) {
                throw new Error("Notification was not persisted");
            }

            await Subscription.publish(ESocketTopic.UserPrivate, new SnowflakeID(notification.receiver_id).toShortCode(), "user:notified", {
                notification: model.api_notification,
            });
        };

        const emailNotification = async (model: TNotificationPublishData) => {
            if (!model.email_template_name || !MAIL_SERVER || !MAIL_FROM || !MAIL_PORT) {
                return;
            }

            const hasUnsubscription = await UserNotificationUnsubscription.hasUnsubscription(model, ENotificationChannel.Email);

            if (hasUnsubscription || !model.target_user?.email) {
                return;
            }

            const resourcePath = path.join(ROOT_DIR, "src/resources/locales", model.target_user.preferred_lang ?? "en-US");
            const templatePath = path.join(resourcePath, `${model.email_template_name}_email.html`);
            const langPath = path.join(resourcePath, "lang.json");

            if (!fs.existsSync(templatePath) || !fs.existsSync(langPath)) {
                return;
            }

            let subject;
            try {
                const locale = Utils.Json.Parse(fs.readFileSync(langPath, "utf-8"));
                subject = locale.subjects[model.email_template_name];
                subject = `[${new Utils.String.Case(PROJECT_NAME).toPascal()}] ${subject}`;
                subject = Utils.String.format(subject, model.email_formats ?? {});
            } catch {
                return;
            }

            const content = Utils.String.format(fs.readFileSync(templatePath, "utf-8"), model.email_formats ?? {});

            await nodemailer
                .createTransport({
                    host: MAIL_SERVER,
                    port: Number(MAIL_PORT),
                    secure: MAIL_SSL_TLS,
                    auth: {
                        user: MAIL_USERNAME,
                        pass: MAIL_PASSWORD,
                    },
                })
                .sendMail({
                    from: `"${MAIL_FROM_NAME}" <${MAIL_FROM}>`,
                    to: model.target_user.email,
                    subject,
                    html: content,
                });
        };

        const mobileNotification = async (model: TNotificationPublishData) => {
            const hasUnsubscription = await UserNotificationUnsubscription.hasUnsubscription(model, ENotificationChannel.Mobile);

            if (hasUnsubscription) {
                return;
            }
        };

        const iotNotification = async (model: TNotificationPublishData) => {
            const hasUnsubscription = await UserNotificationUnsubscription.hasUnsubscription(model, ENotificationChannel.IoT);

            if (hasUnsubscription) {
                return;
            }
        };

        if (!Utils.Type.isObject<TNotificationPublishData>(data)) {
            return;
        }

        const model = convertBigIntToString(data);

        if (!model.notification || !model.target_user || !model.notification.notification_type) {
            return;
        }

        if (model.web_handled_by_python !== true) {
            await webNotification(model);
        }
        await emailNotification(model);
        await mobileNotification(model);
        await iotNotification(model);
    },
    "side_effect"
);
