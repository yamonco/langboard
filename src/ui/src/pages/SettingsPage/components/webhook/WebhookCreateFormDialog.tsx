import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Dialog from "@/components/base/Dialog";
import Floating from "@/components/base/Floating";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import CopyInput from "@/components/CopyInput";
import FormErrorMessage from "@/components/FormErrorMessage";
import useCreateWebhook from "@/controllers/api/settings/webhooks/useCreateWebhook";
import useGetWebhookEvents, { IWebhookEventOption } from "@/controllers/api/settings/webhooks/useGetWebhookEvents";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import WebhookEventSelector from "@/pages/SettingsPage/components/webhook/WebhookEventSelector";
import { ISharedSettingsModalProps } from "@/pages/SettingsPage/types";
import { EHttpStatus } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";

/** Creates a webhook and keeps its one-time signing secret visible until explicitly closed. */
function WebhookCreateFormDialog({ opened, setOpened }: ISharedSettingsModalProps): React.JSX.Element {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const [isValidating, setIsValidating] = useState(false);
    const nameInputRef = useRef<HTMLInputElement>(null);
    const urlInputRef = useRef<HTMLInputElement>(null);
    const { mutate } = useCreateWebhook();
    const { mutate: getWebhookEvents } = useGetWebhookEvents({ interceptToast: true });
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [allEvents, setAllEvents] = useState(true);
    const [selectedEvents, setSelectedEvents] = useState<string[]>([]);
    const [eventOptions, setEventOptions] = useState<IWebhookEventOption[]>([]);
    const [revealedSecret, setRevealedSecret] = useState<string | null>(null);

    useEffect(() => {
        if (!opened || eventOptions.length) {
            return;
        }

        getWebhookEvents(
            {},
            {
                onSuccess: setEventOptions,
            }
        );
    }, [opened, eventOptions.length, getWebhookEvents]);

    const reset = () => {
        if (nameInputRef.current) {
            nameInputRef.current.value = "";
        }
        if (urlInputRef.current) {
            urlInputRef.current.value = "";
        }
        setErrors({});
        setAllEvents(true);
        setSelectedEvents([]);
        setRevealedSecret(null);
    };

    const save = () => {
        if (isValidating || !nameInputRef.current || !urlInputRef.current) {
            return;
        }

        setIsValidating(true);

        const nameValue = nameInputRef.current.value.trim();
        const urlValue = urlInputRef.current.value.trim();
        const newErrors: Record<string, string> = {};
        let focusableInput: HTMLInputElement | null = null;

        if (!nameValue) {
            newErrors.name = t("settings.errors.missing.webhook_name");
            focusableInput = nameInputRef.current;
        }

        if (!Utils.String.isValidURL(urlValue)) {
            newErrors.url = t("settings.errors.invalid.webhook_url");
            if (!focusableInput) {
                focusableInput = urlInputRef.current;
            }
        }

        if (!urlValue) {
            newErrors.url = t("settings.errors.missing.webhook_url");
            if (!focusableInput) {
                focusableInput = urlInputRef.current;
            }
        }

        if (!allEvents && selectedEvents.length === 0) {
            newErrors.events = t("settings.Select at least one webhook event.");
        }

        if (Object.keys(newErrors).length) {
            setErrors(newErrors);
            setIsValidating(false);
            focusableInput?.focus();
            return;
        }

        mutate(
            {
                name: nameValue,
                url: urlValue,
                events: allEvents ? null : selectedEvents,
            },
            {
                onSuccess: ({ revealed_value }) => {
                    Toast.Add.success(t("successes.Webhook created successfully."));
                    setRevealedSecret(revealed_value);
                },
                onError: (error) => {
                    const { handle } = setupApiErrorHandler({
                        [EHttpStatus.HTTP_403_FORBIDDEN]: {
                            after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_403_FORBIDDEN), { replace: true }),
                        },
                    });

                    handle(error);
                },
                onSettled: () => {
                    setIsValidating(false);
                },
            }
        );
    };

    const changeOpenedState = (nextOpened: bool) => {
        if (isValidating) {
            return;
        }

        setOpened(nextOpened);
        if (!nextOpened) {
            reset();
        }
    };

    return (
        <Dialog.Root open={opened} onOpenChange={changeOpenedState}>
            <Dialog.Content className="sm:max-w-md" aria-describedby="">
                <Dialog.Header>
                    <Dialog.Title>{t("settings.Create webhook")}</Dialog.Title>
                </Dialog.Header>
                {revealedSecret ? (
                    <>
                        <Box mt="4" as="p" textSize="sm" className="text-muted-foreground">
                            {t("settings.Copy this signing secret now. It will not be shown again.")}
                        </Box>
                        <Box mt="3">
                            <CopyInput value={revealedSecret} />
                        </Box>
                        <Dialog.Footer className="mt-6">
                            <Button type="button" onClick={() => changeOpenedState(false)}>
                                {t("common.Close")}
                            </Button>
                        </Dialog.Footer>
                    </>
                ) : (
                    <>
                        <Box mt="4">
                            <Floating.LabelInput
                                label={t("settings.Webhook name")}
                                autoFocus
                                autoComplete="off"
                                disabled={isValidating}
                                required
                                ref={nameInputRef}
                            />
                            {errors.name && <FormErrorMessage error={errors.name} notInForm />}
                        </Box>
                        <Box mt="4">
                            <Floating.LabelInput
                                label={t("settings.Webhook URL")}
                                autoComplete="off"
                                disabled={isValidating}
                                required
                                ref={urlInputRef}
                            />
                            {errors.url && <FormErrorMessage error={errors.url} notInForm />}
                        </Box>
                        <WebhookEventSelector
                            allEvents={allEvents}
                            setAllEvents={setAllEvents}
                            selectedEvents={selectedEvents}
                            setSelectedEvents={setSelectedEvents}
                            options={eventOptions}
                            disabled={isValidating}
                            error={errors.events}
                        />
                        <Dialog.Footer className="mt-6 flex-col gap-2 sm:justify-end sm:gap-0">
                            <Dialog.Close asChild>
                                <Button type="button" variant="secondary" disabled={isValidating}>
                                    {t("common.Cancel")}
                                </Button>
                            </Dialog.Close>
                            <SubmitButton type="button" isValidating={isValidating} onClick={save}>
                                {t("common.Create")}
                            </SubmitButton>
                        </Dialog.Footer>
                    </>
                )}
            </Dialog.Content>
        </Dialog.Root>
    );
}

export default WebhookCreateFormDialog;
