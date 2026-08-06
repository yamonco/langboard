import Box from "@/components/base/Box";
import Checkbox from "@/components/base/Checkbox";
import MultiSelect from "@/components/MultiSelect";
import { IWebhookEventOption } from "@/controllers/api/settings/webhooks/useGetWebhookEvents";
import FormErrorMessage from "@/components/FormErrorMessage";
import { useTranslation } from "react-i18next";

interface IWebhookEventSelectorProps {
    allEvents: bool;
    setAllEvents: (value: bool) => void;
    selectedEvents: string[];
    setSelectedEvents: (value: string[]) => void;
    options: IWebhookEventOption[];
    disabled?: bool;
    error?: string;
}

/** Selects either every webhook event or an explicit non-empty allowlist. */
function WebhookEventSelector({
    allEvents,
    setAllEvents,
    selectedEvents,
    setSelectedEvents,
    options,
    disabled,
    error,
}: IWebhookEventSelectorProps): React.JSX.Element {
    const [t] = useTranslation();

    return (
        <Box mt="4">
            <Checkbox
                checked={allEvents}
                onCheckedChange={(checked) => setAllEvents(checked === true)}
                disabled={disabled}
                label={t("settings.All webhook events")}
                description={t("settings.Deliver every current and future webhook event.")}
            />
            {!allEvents && (
                <Box mt="3">
                    <MultiSelect
                        selections={options}
                        selectedValue={selectedEvents}
                        onValueChange={setSelectedEvents}
                        placeholder={t("settings.Select webhook events")}
                        disabled={disabled}
                    />
                    {error && <FormErrorMessage error={error} notInForm />}
                </Box>
            )}
        </Box>
    );
}

export default WebhookEventSelector;
