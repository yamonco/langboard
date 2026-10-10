import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";
import { QUERY_NAMES, SIGN_IN_TOKEN_LENGTH } from "@/constants";
import { FormOnlyLayout } from "@/components/Layout";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import useAuthEmail from "@/controllers/api/auth/useAuthEmail";
import useValidateRecoveryToken from "@/controllers/api/auth/useValidateRecoveryToken";
import { ROUTES } from "@/core/routing/constants";
import ResetPasswordForm from "@/pages/auth/AccountRecoveryPage/ResetPasswordForm";
import SendResetLinkForm from "@/pages/auth/AccountRecoveryPage/SendResetLinkForm";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { EHttpStatus } from "@langboard/core/enums";

function AccountRecoveryPage(): React.JSX.Element {
    const { setPageAliasRef } = usePageHeader();
    const [t] = useTranslation();
    const location = useLocation();
    const navigate = usePageNavigateRef();
    const [email, setEmail] = useState<string | null>(location.state?.email);
    const [[form, description], setPage] = useState<[React.JSX.Element | null, string]>([null, ""]);
    const { mutate: validateRecoveryTokenMutate } = useValidateRecoveryToken();
    const { mutate: checkEmailMutate } = useAuthEmail();

    const backToSignin = () => {
        const searchParams = new URLSearchParams(location.search);
        navigate(`${ROUTES.SIGN_IN.PASSWORD}?${searchParams.toString()}`, { smooth: true });
    };

    useEffect(() => {
        setPageAliasRef.current("Account Recovery");
        const searchParams = new URLSearchParams(location.search);
        const signTokenParam = searchParams.get(QUERY_NAMES.SIGN_IN_TOKEN);
        const emailTokenParam = searchParams.get(QUERY_NAMES.EMAIL_TOKEN);
        const recoveryTokenParam = searchParams.get(QUERY_NAMES.RECOVERY_TOKEN);

        if (location.pathname === ROUTES.ACCOUNT_RECOVERY.RESET) {
            if (!recoveryTokenParam) {
                searchParams.delete(QUERY_NAMES.RECOVERY_TOKEN);
                navigate(ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND), { replace: true, smooth: true });
                return;
            }

            if (!email) {
                validateRecoveryTokenMutate(
                    { recovery_token: recoveryTokenParam },
                    {
                        onSuccess: (data) => {
                            if (email !== data.email) {
                                setEmail(data.email);
                            }
                        },
                        onError: () => {
                            navigate(ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND), { replace: true, smooth: true });
                        },
                    }
                );
            }

            return;
        }

        if (!signTokenParam || signTokenParam.length !== SIGN_IN_TOKEN_LENGTH || !emailTokenParam) {
            searchParams.delete(QUERY_NAMES.SIGN_IN_TOKEN);
            searchParams.delete(QUERY_NAMES.EMAIL_TOKEN);
            navigate(`${ROUTES.SIGN_IN.EMAIL}?${searchParams.toString()}`, { replace: true, smooth: true });
            return;
        }

        if (!email) {
            checkEmailMutate(
                { is_token: true, token: emailTokenParam, sign_token: signTokenParam },
                {
                    onSuccess: (data) => {
                        if (!data.token) {
                            throw new Error();
                        }

                        if (email !== data.email) {
                            setEmail(data.email);
                        }
                    },
                    onError: () => {
                        backToSignin();
                    },
                }
            );
        }
    }, [location]);

    useEffect(() => {
        const searchParams = new URLSearchParams(location.search);
        const signTokenParam = searchParams.get(QUERY_NAMES.SIGN_IN_TOKEN);
        const emailTokenParam = searchParams.get(QUERY_NAMES.EMAIL_TOKEN);
        const recoveryTokenParam = searchParams.get(QUERY_NAMES.RECOVERY_TOKEN);

        switch (location.pathname) {
            case ROUTES.ACCOUNT_RECOVERY.NAME:
                if (!signTokenParam || !emailTokenParam) {
                    return;
                }

                setPage([
                    <SendResetLinkForm signToken={signTokenParam} emailToken={emailTokenParam} backToSignin={backToSignin} />,
                    t("accountRecovery.Please enter your name to verify your account."),
                ]);
                break;
            case ROUTES.ACCOUNT_RECOVERY.RESET:
                if (!recoveryTokenParam) {
                    return;
                }

                setPage([
                    <ResetPasswordForm recoveryToken={recoveryTokenParam} backToSignin={backToSignin} />,
                    t("accountRecovery.Please enter your new password."),
                ]);
                break;
        }
    }, [location, email]);

    if (location.state?.isTwoSidedView ?? true) {
        const leftSide = (
            <>
                <h2 className="text-4xl font-normal">{t("accountRecovery.Password recovery")}</h2>
                <Box mt="4" textSize="base">
                    {description}
                </Box>
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-4"
                    onClick={backToSignin}
                    title={t("common.Sign in with email", { email })}
                >
                    {email}
                </Button>
            </>
        );

        return <FormOnlyLayout leftSide={leftSide} rightSide={form} useLogo size="sm" />;
    } else {
        return (
            <FormOnlyLayout size="sm" useLogo>
                {form}
            </FormOnlyLayout>
        );
    }
}

export default AccountRecoveryPage;
