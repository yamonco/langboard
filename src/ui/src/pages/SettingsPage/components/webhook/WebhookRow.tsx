import Checkbox from "@/components/base/Checkbox";
import Table from "@/components/base/Table";
import { IFlexProps } from "@/components/base/Flex";
import DateDistance from "@/components/DateDistance";
import { WebhookModel } from "@/core/models";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import WebhookName from "@/pages/SettingsPage/components/webhook/WebhookName";
import WebhookURL from "@/pages/SettingsPage/components/webhook/WebhookURL";
import WebhookEvents from "@/pages/SettingsPage/components/webhook/WebhookEvents";
import { memo } from "react";

export interface IWebhookRowProps extends IFlexProps {
    webhook: WebhookModel.TModel;
    selectedWebhooks: string[];
    setSelectedWebhooks: React.Dispatch<React.SetStateAction<string[]>>;
}

const WebhookRow = memo(({ webhook, selectedWebhooks, setSelectedWebhooks, ...props }: IWebhookRowProps) => {
    const createdAt = webhook.useField("created_at");
    const lastUsedAt = webhook.useField("last_used_at");

    const toggleSelect = () => {
        setSelectedWebhooks((prev) => {
            if (prev.some((value) => value === webhook.uid)) {
                return prev.filter((value) => value !== webhook.uid);
            } else {
                return [...prev, webhook.uid];
            }
        });
    };

    return (
        <Table.FlexRow {...props}>
            <ModelRegistry.WebhookModel.Provider model={webhook}>
                <Table.FlexCell className="w-12 text-center">
                    <Checkbox checked={selectedWebhooks.some((value) => value === webhook.uid)} onClick={toggleSelect} />
                </Table.FlexCell>
                <WebhookName />
                <WebhookURL />
                <WebhookEvents />
                <Table.FlexCell className="w-1/6 truncate text-center">
                    <DateDistance date={createdAt} />
                </Table.FlexCell>
                <Table.FlexCell className="w-1/6 truncate text-center">{lastUsedAt ? <DateDistance date={lastUsedAt} /> : "-"}</Table.FlexCell>
            </ModelRegistry.WebhookModel.Provider>
        </Table.FlexRow>
    );
});

export default WebhookRow;
