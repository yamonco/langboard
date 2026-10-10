import "@/assets/styles/main.css";
import "@/i18n";
import "@/core/injection/StringExtensions";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import Toast from "@/components/base/Toast";
import useChangeCardDetails from "@/controllers/api/card/useChangeCardDetails";
import { InlineDeadlineField } from "./BoardCardInlineDeadline";
function Fixture() {
    const params = new URLSearchParams(location.search);
    const [deadline, setDeadline] = useState<Date | undefined>(params.has("existing") ? new Date("2030-06-15T12:00:00Z") : undefined);
    const { mutateAsync } = useChangeCardDetails({ interceptToast: true });
    return (
        <main className="mx-auto max-w-md p-4">
            <InlineDeadlineField
                deadline={deadline}
                canEdit={!params.has("readonly")}
                save={async (value) => {
                    await mutateAsync({ project_uid: "fixture-board", card_uid: "fixture-card", deadline_at: value });
                    setDeadline(value || undefined);
                }}
            />
            <output>{deadline?.toISOString() ?? "empty"}</output>
            <Toast.Area />
        </main>
    );
}
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <Fixture />
    </QueryClientProvider>
);
