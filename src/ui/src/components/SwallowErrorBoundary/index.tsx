import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Dialog from "@/components/base/Dialog";
import Toast from "@/components/base/Toast";
import React from "react";
import { t } from "i18next";

interface TProps {
    children?: React.ReactNode;
}

interface TState {
    error: Error | null;
}

let lastErrorOccurred = 0;
let lastError: Error | null = null;
let clearLastErrorTimeout: NodeJS.Timeout | null = null;
class SwallowErrorBoundary extends React.Component<TProps, TState> {
    constructor(props: TProps) {
        super(props);
        this.state = { error: null };
    }

    static getDerivedStateFromError(_: Error): TState {
        return { error: null };
    }

    componentDidCatch(error: Error): void {
        console.error('[SwallowErrorBoundary]', error);
        if (lastError && error.message === lastError.message) {
            ++lastErrorOccurred;
            return;
        }

        if (clearLastErrorTimeout) {
            clearTimeout(clearLastErrorTimeout);
            clearLastErrorTimeout = null;
        }

        lastError = error;
        clearLastErrorTimeout = setTimeout(() => {
            lastError = null;
            if (clearLastErrorTimeout) {
                clearTimeout(clearLastErrorTimeout);
            }
            clearLastErrorTimeout = null;
        }, 1000 * 5);

        Toast.Add.error(t("errors.A rendering error occurred."), {
            description: t("errors.Please report this issue to the developers that how you got this error."),
        });
    }

    render() {
        if (lastErrorOccurred > 5) {
            return (
                <Dialog.Root open>
                    <Dialog.Content>
                        <Dialog.Header>
                            <Dialog.Title>{t("errors.A rendering error occurred.")}</Dialog.Title>
                        </Dialog.Header>
                        <Dialog.Description asChild>
                            <Box mt="2">
                                <Box>{t("errors.Too many errors occurred.")}</Box>
                                <Box>{t("errors.Please report this issue to the developers that how you got this error.")}</Box>
                            </Box>
                        </Dialog.Description>
                        <Dialog.Footer className="mt-2">
                            <Button
                                size="sm"
                                onClick={() => {
                                    window.location.reload();
                                }}
                            >
                                {t("common.Refresh")}
                            </Button>
                        </Dialog.Footer>
                    </Dialog.Content>
                </Dialog.Root>
            );
        }

        return this.props.children;
    }
}

export default SwallowErrorBoundary;
