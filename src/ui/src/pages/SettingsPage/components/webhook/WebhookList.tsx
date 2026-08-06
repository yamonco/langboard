import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Checkbox from "@/components/base/Checkbox";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Loading from "@/components/base/Loading";
import InfiniteScroller from "@/components/InfiniteScroller";
import useInfiniteScrollPager from "@/core/hooks/useInfiniteScrollPager";
import useScrollToTop from "@/core/hooks/useScrollToTop";
import { WebhookModel } from "@/core/models";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import WebhookRow from "@/pages/SettingsPage/components/webhook/WebhookRow";
import { useReducer } from "react";
import { useTranslation } from "react-i18next";

export interface IWebhookListProps {
    selectedWebhooks: string[];
    setSelectedWebhooks: React.Dispatch<React.SetStateAction<string[]>>;
}

function WebhookList({ selectedWebhooks, setSelectedWebhooks }: IWebhookListProps) {
    const [t] = useTranslation();
    const { scrollableRef, isAtTop, scrollToTop } = useScrollToTop({});
    const updater = useReducer((x) => x + 1, 0);
    const rawWebhooks = WebhookModel.Model.useModels(() => true);
    const PAGE_SIZE = 30;
    const { items: webhooks, nextPage, hasMore } = useInfiniteScrollPager({ allItems: rawWebhooks, size: PAGE_SIZE, updater });

    const selectAll = () => {
        setSelectedWebhooks((prev) => {
            if (prev.length === webhooks.length) {
                return [];
            } else {
                return webhooks.map((webhook) => webhook.uid);
            }
        });
    };

    return (
        <Box position="relative" h="full">
            <Box
                className={cn(
                    "max-h-[calc(100vh_-_theme(spacing.40))]",
                    "md:max-h-[calc(100vh_-_theme(spacing.44))]",
                    "lg:max-h-[calc(100vh_-_theme(spacing.48))]",
                    "overflow-y-auto"
                )}
                ref={scrollableRef}
            >
                <InfiniteScroller.Table.Default
                    columns={[
                        {
                            name: <Checkbox checked={!!webhooks.length && webhooks.length === selectedWebhooks.length} onClick={selectAll} />,
                            className: "w-12 text-center",
                        },
                        { name: t("settings.Name"), className: "w-1/6 text-center" },
                        { name: t("settings.URL"), className: "w-[calc(calc(100%_/_6_*_2)_-_theme(spacing.12))] text-center" },
                        { name: t("settings.Events"), className: "w-1/6 text-center" },
                        { name: t("settings.Created"), className: "w-1/6 text-center" },
                        { name: t("settings.Last Used"), className: "w-1/6 text-center" },
                    ]}
                    headerClassName="sticky top-0 z-50 bg-background"
                    scrollable={() => scrollableRef.current}
                    loadMore={nextPage}
                    hasMore={hasMore}
                    totalCount={webhooks.length}
                    loader={
                        <Flex justify="center" py="6" key={Utils.String.Token.shortUUID()}>
                            <Loading variant="secondary" />
                        </Flex>
                    }
                >
                    {webhooks.map((webhook) => (
                        <WebhookRow
                            key={webhook.uid}
                            webhook={webhook}
                            selectedWebhooks={selectedWebhooks}
                            setSelectedWebhooks={setSelectedWebhooks}
                        />
                    ))}
                </InfiniteScroller.Table.Default>
                {!webhooks.length && (
                    <Flex justify="center" items="center" h="full" mt="2">
                        {t("settings.No webhooks")}
                    </Flex>
                )}
                {!isAtTop && (
                    <Button
                        onClick={scrollToTop}
                        size="icon"
                        variant="outline"
                        className="absolute bottom-2 left-1/2 inline-flex -translate-x-1/2 transform rounded-full shadow-md"
                    >
                        <IconComponent icon="arrow-up" size="4" />
                    </Button>
                )}
            </Box>
        </Box>
    );
}

export default WebhookList;
