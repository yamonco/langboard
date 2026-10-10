/* eslint-disable @typescript-eslint/no-explicit-any */
import { useTranslation } from "react-i18next";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Checkbox from "@/components/base/Checkbox";
import Dialog from "@/components/base/Dialog";
import Flex from "@/components/base/Flex";
import Floating from "@/components/base/Floating";
import Form from "@/components/base/Form";
import Label from "@/components/base/Label";
import Select from "@/components/base/Select";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import FormErrorMessage from "@/components/FormErrorMessage";
import { useRef, useState } from "react";
import useCreateApiKey from "@/controllers/api/settings/apiKeys/useCreateApiKey";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ROUTES } from "@/core/routing/constants";
import CopyInput from "@/components/CopyInput";
import MultiSelect from "@/components/MultiSelect";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { EHttpStatus } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";
import { ApiKeySettingModel } from "@/core/models";
import { ISharedSettingsModalProps } from "@/pages/SettingsPage/types";

function ApiKeyCreateFormDialog({ opened, setOpened }: ISharedSettingsModalProps): React.JSX.Element {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const [isValidating, setIsValidating] = useState(false);
    const [revealedKey, setRevealedKey] = useState<string>();
    const inputsRef = useRef({ name: null as HTMLInputElement | null });
    const setInputRef = (key: keyof typeof inputsRef.current) => (el: HTMLElement | null) => {
        inputsRef.current[key] = el as any;
    };
    const [isActive, setIsActive] = useState(true);
    const { mutate } = useCreateApiKey();
    const [errors, setErrors] = useState<Record<string, string>>({});
    const ipWhitelistRef = useRef<string[]>([]);
    const [isAllAllowedIP, setIsAllAllowedIP] = useState(false);
    const [expiresInDays, setExpiresInDays] = useState<string | null>(null);
    const save = () => {
        if (isValidating || !inputsRef.current.name) {
            return;
        }

        setIsValidating(true);

        const values = {} as Record<keyof typeof inputsRef.current, string>;
        const newErrors = {} as Record<keyof typeof inputsRef.current, string>;
        let focusableInput = null as HTMLInputElement | HTMLTextAreaElement | null;

        const shouldValidateInputs: (keyof typeof inputsRef.current)[] = ["name"];
        shouldValidateInputs.forEach((key) => {
            const input = inputsRef.current[key] as HTMLInputElement | HTMLTextAreaElement;
            if (!input) {
                return;
            }

            const value = input!.value.trim();
            if (!value) {
                newErrors[key as keyof typeof inputsRef.current] = t(`settings.errors.missing.api_key_${key}`);
                if (!focusableInput) {
                    focusableInput = input;
                }
            } else {
                values[key] = value;
            }
        });

        if (Object.keys(newErrors).length) {
            setErrors(newErrors);
            setIsValidating(false);
            focusableInput?.focus();
            return;
        }

        mutate(
            {
                name: values.name,
                ip_whitelist: ipWhitelistRef.current.join(","),
                is_active: isActive,
                expires_in_days: expiresInDays,
            },
            {
                onSuccess: (data) => {
                    Toast.Add.success(t("successes.API key created successfully."));
                    if (data?.key) {
                        setRevealedKey(data.key);
                    }
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

    const changeOpenedState = (opened: bool) => {
        if (isValidating) {
            return;
        }

        setRevealedKey(undefined);
        setOpened(opened);
    };

    return (
        <Dialog.Root open={opened} onOpenChange={changeOpenedState}>
            <Dialog.Content className="sm:max-w-md" aria-describedby="">
                <Dialog.Header>
                    <Dialog.Title>{t("settings.Create API key")}</Dialog.Title>
                </Dialog.Header>
                {!revealedKey && (
                    <Form.Root className="mt-4">
                        <Box mt="10">
                            <Floating.LabelInput
                                label={t("settings.Name")}
                                autoFocus
                                autoComplete="off"
                                required
                                disabled={isValidating}
                                ref={setInputRef("name")}
                            />
                            {errors.name && <FormErrorMessage error={errors.name} notInForm />}
                        </Box>
                        <Flex mt="4" items="center" gap="2">
                            <MultiSelect
                                selections={[]}
                                placeholder={t("settings.Add a new IP address or range (e.g. 192.0.0.1 or 192.0.0.0/24)...")}
                                selectedValue={[]}
                                onValueChange={(values) => {
                                    ipWhitelistRef.current = values;
                                }}
                                className="w-[calc(100%_-_theme(spacing.24))]"
                                inputClassName="ml-1 placeholder:text-gray-500 placeholder:font-medium"
                                canCreateNew
                                validateCreatedNewValue={Utils.String.isValidIpv4OrRange}
                                createNewCommandItemLabel={(value) => {
                                    const newIPs: string[] = [];

                                    if (value.includes("/24")) {
                                        newIPs.push(value, value.replace("/24", ""));
                                    } else {
                                        newIPs.push(value, `${value}/24`);
                                    }

                                    return newIPs.map((ip) => ({
                                        label: ip,
                                        value: ip,
                                    }));
                                }}
                                isNewCommandItemMultiple
                                disabled={isValidating || isAllAllowedIP}
                            />
                            <Label display="flex" items="center" gap="1.5" w="20" mb="2" cursor="pointer">
                                <Checkbox
                                    onCheckedChange={(checked) => {
                                        if (Utils.Type.isString(checked)) {
                                            return;
                                        }

                                        if (checked) {
                                            ipWhitelistRef.current = [ApiKeySettingModel.ALLOWED_ALL_IPS];
                                        } else {
                                            ipWhitelistRef.current = [];
                                        }

                                        setIsAllAllowedIP(checked);
                                    }}
                                />
                                {t("settings.Allow all")}
                            </Label>
                        </Flex>
                        <Box mt="4">
                            <Floating.LabelSelect
                                label={t("settings.Expires in")}
                                value={expiresInDays ?? "never"}
                                onValueChange={(value) => {
                                    setExpiresInDays(value);
                                }}
                                disabled={isValidating}
                                options={
                                    <>
                                        <Select.Item value="never">{t("settings.Never")}</Select.Item>
                                        <Select.Item value="30">30 {t("common.days")}</Select.Item>
                                        <Select.Item value="60">60 {t("common.days")}</Select.Item>
                                        <Select.Item value="90">90 {t("common.days")}</Select.Item>
                                        <Select.Item value="180">180 {t("common.days")}</Select.Item>
                                        <Select.Item value="365">365 {t("common.days")}</Select.Item>
                                    </>
                                }
                            />
                        </Box>
                        <Box mt="4">
                            <Label display="flex" items="center" gap="1.5" cursor="pointer">
                                <Checkbox
                                    checked={isActive}
                                    onCheckedChange={(checked) => {
                                        if (!Utils.Type.isString(checked)) {
                                            setIsActive(checked);
                                        }
                                    }}
                                    disabled={isValidating}
                                />
                                {t("settings.Active")}
                            </Label>
                        </Box>
                    </Form.Root>
                )}
                {revealedKey && <CopyInput value={revealedKey} className="mt-4" />}
                <Dialog.Footer className="mt-6 flex-col gap-2 sm:justify-end sm:gap-0">
                    <Dialog.Close asChild>
                        <Button type="button" variant={!revealedKey ? "destructive" : "outline"} disabled={isValidating}>
                            {t(!revealedKey ? "common.Cancel" : "common.Close")}
                        </Button>
                    </Dialog.Close>
                    {!revealedKey && (
                        <SubmitButton type="button" isValidating={isValidating} onClick={save}>
                            {t("common.Create")}
                        </SubmitButton>
                    )}
                </Dialog.Footer>
            </Dialog.Content>
        </Dialog.Root>
    );
}

export default ApiKeyCreateFormDialog;
