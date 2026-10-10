import { useEffect, useRef } from "react";
import { useLocation } from "react-router";
import { useTranslation } from "react-i18next";
import { FormOnlyLayout, createTwoSidedSizeClassNames } from "@/components/Layout";
import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import Toast from "@/components/base/Toast";
import { QUERY_NAMES } from "@/constants";
import useOidcCallback from "@/controllers/api/auth/useOidcCallback";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { useAuth } from "@/core/providers/AuthProvider";
import { ROUTES } from "@/core/routing/constants";
import { getAuthStore } from "@/core/stores/AuthStore";

function OidcCallbackPage(): React.JSX.Element {
    const [t] = useTranslation();
    const location = useLocation();
    const navigate = usePageNavigateRef();
    const { signIn } = useAuth();
    const { mutateAsync } = useOidcCallback({ interceptToast: true });
    const { wrapper: wrapperClassName, width: widthClassName } = createTwoSidedSizeClassNames("sm");
    const handledRequestKeyRef = useRef<string | null>(null);

    useEffect(() => {
        let isDisposed = false;
        const searchParams = new URLSearchParams(location.search);
        const code = searchParams.get("code");
        const state = searchParams.get("state");

        if (!code || !state) {
            Toast.Add.error(t("auth.OIDC sign-in failed. Please try again."));
            navigate(`${ROUTES.SIGN_IN.EMAIL}?${searchParams.toString()}`, { replace: true, smooth: true });
            return;
        }

        const requestKey = `oidc-callback:${code}:${state}`;
        if (handledRequestKeyRef.current === requestKey) {
            return;
        }
        if (getAuthStore().getOidcCallbackRequestStatus(requestKey) === "pending") {
            handledRequestKeyRef.current = requestKey;
            return;
        }

        handledRequestKeyRef.current = requestKey;
        getAuthStore().setOidcCallbackRequestStatus(requestKey, "pending");

        void mutateAsync({ code, state })
            .then((data) => {
                if (!data.access_token) {
                    throw new Error();
                }
                if (isDisposed) {
                    return;
                }

                const fallbackRedirectUrl = searchParams.get(QUERY_NAMES.REDIRECT) ?? ROUTES.AFTER_SIGN_IN;
                const redirectUrl = data.redirect ?? fallbackRedirectUrl;
                let parsedRedirectUrl = redirectUrl;
                try {
                    parsedRedirectUrl = decodeURIComponent(redirectUrl);
                } catch {
                    parsedRedirectUrl = redirectUrl;
                }

                void signIn(data.access_token, () =>
                    navigate(parsedRedirectUrl, {
                        replace: true,
                        smooth: true,
                    })
                );
                getAuthStore().setOidcCallbackRequestStatus(requestKey, "done");
            })
            .catch(() => {
                handledRequestKeyRef.current = null;
                getAuthStore().removeOidcCallbackRequestStatus(requestKey);
                if (isDisposed) {
                    return;
                }

                searchParams.delete("code");
                searchParams.delete("state");
                Toast.Add.error(t("auth.OIDC sign-in failed. Please try again."));
                navigate(`${ROUTES.SIGN_IN.EMAIL}?${searchParams.toString()}`, { replace: true, smooth: true });
            });

        return () => {
            isDisposed = true;
        };
        // OIDC callback handling should only rerun when the callback query string changes.
    }, [location]);

    return (
        <FormOnlyLayout size="default" useLogo>
            <Flex className={wrapperClassName}>
                <Box className={widthClassName}>
                    <h2 className="text-4xl font-normal">{t("auth.Signing in with SSO...")}</h2>
                </Box>
            </Flex>
        </FormOnlyLayout>
    );
}

export default OidcCallbackPage;
