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

const BOUNDARY_INSTANCE_RETRY_LIMIT = 3;

class SwallowErrorBoundary extends React.Component<TProps, TState> {
    private instanceErrorCount = 0;

    constructor(props: TProps) {
        super(props);
        this.state = { error: null };
    }

    static getDerivedStateFromError(_: Error): TState {
        return { error: null };
    }

    componentDidCatch(error: Error): void {
        console.error('[SwallowErrorBoundary]', error);
        this.instanceErrorCount += 1;

        if (lastError && error.message === lastError.message) {
            ++lastErrorOccurred;
            return;
        }

        if (clearLastErrorTimeout) {
            clearTimeout(clearLastErrorTimeout);
            clearLastErrorTimeout = null;
        }

        lastError = error;
        lastErrorOccurred = 1;
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

    private handleRetry = (): void => {
        this.instanceErrorCount = 0;
        this.forceUpdate();
    };

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

        // A repeatedly crashing subtree must not re-render forever: cap retries
        // per boundary instance and fall back to a small inline error with a
        // manual retry so the rest of the page stays usable.
        if (this.instanceErrorCount >= BOUNDARY_INSTANCE_RETRY_LIMIT) {
            return (
                <Box className="flex items-center gap-2 rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                    <span>{t("errors.This section failed to render.")}</span>
                    <Button size="sm" variant="outline" onClick={this.handleRetry}>
                        {t("common.Retry")}
                    </Button>
                </Box>
            );
        }

        return this.props.children;
    }
}

export default SwallowErrorBoundary;
