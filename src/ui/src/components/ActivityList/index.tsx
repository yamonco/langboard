import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Loading from "@/components/base/Loading";
import InfiniteScroller from "@/components/InfiniteScroller";
import { TGetActivitiesForm } from "@/controllers/api/shared/types";
import useCreateActivityTimeline, { TActivityViewType } from "@/core/hooks/activity/useCreateActivityTimeline";
import { ActivityModel, AuthUser } from "@/core/models";
import { InfiniteRefreshableListProvider, useInfiniteRefreshableList } from "@/core/providers/InfiniteRefreshableListProvider";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";

export interface IActivityListProps extends Pick<React.ComponentProps<typeof InfiniteScroller.Default>, "as"> {
    form: TGetActivitiesForm;
    currentUser: AuthUser.TModel;
    className?: string;
    outerClassName?: string;
    outerStyle?: React.CSSProperties;
    viewType?: TActivityViewType;
}

const PAGE_LIMIT = 15;

function ActivityList({ form, ...props }: IActivityListProps) {
    const activityFilter = useMemo(() => {
        if (form.assignee_uid) {
            return (model: ActivityModel.TModel) => model.filterable_map.user === form.assignee_uid || model.filterable_map.bot === form.assignee_uid;
        }

        switch (form.type) {
            case "user":
                return (model: ActivityModel.TModel) => model.filterable_map.user === form.user_uid || model.filterable_map.bot === form.user_uid;
            case "project":
                return (model: ActivityModel.TModel) => model.filterable_map.project === form.project_uid;
            case "project_column":
                return (model: ActivityModel.TModel) =>
                    model.filterable_map.project === form.project_uid && model.filterable_map.project_column === form.project_column_uid;
            case "card":
                return (model: ActivityModel.TModel) =>
                    model.filterable_map.project === form.project_uid && model.filterable_map.card === form.card_uid;
            case "project_wiki":
                return (model: ActivityModel.TModel) =>
                    model.filterable_map.project === form.project_uid && model.filterable_map.project_wiki === form.wiki_uid;
            default:
                throw new Error("Invalid activity type");
        }
    }, [form]);
    const activities = ActivityModel.Model.useModels(activityFilter, [activityFilter]);

    return (
        <InfiniteRefreshableListProvider
            models={activities}
            form={form}
            limit={PAGE_LIMIT}
            prepareData={(models, data) => {
                if (!data.references) {
                    return;
                }

                for (let i = 0; i < models.length; ++i) {
                    models[i].references = data.references;
                }
            }}
        >
            <ActivityListDisplay {...props} />
        </InfiniteRefreshableListProvider>
    );
}

function ActivityListDisplay({
    as,
    currentUser,
    className,
    outerClassName,
    outerStyle,
    viewType,
}: Omit<IActivityListProps, "form">): React.JSX.Element {
    const [t] = useTranslation();
    const {
        models: activities,
        listIdRef,
        isLastPage,
        countNewRecords,
        isRefreshing,
        nextPage,
        refreshList,
        checkOutdatedOnScroll,
    } = useInfiniteRefreshableList<"ActivityModel">();
    const { SkeletonActivity, ActivityTimeline } = useCreateActivityTimeline(currentUser, viewType);

    return (
        <Box position="relative" className={className}>
            {!activities.length && (
                <Flex justify="center" items="center" h="full">
                    {t("activity.No activities")}
                </Flex>
            )}
            <Box id={listIdRef.current} className={cn(outerClassName, "overflow-y-auto")} style={outerStyle} onScroll={checkOutdatedOnScroll}>
                {isRefreshing && <Loading variant="secondary" size="4" my="2" />}
                <InfiniteScroller.Default
                    as={as}
                    row={Box}
                    scrollable={() => document.getElementById(listIdRef.current)}
                    loadMore={nextPage}
                    loader={<SkeletonActivity key={Utils.String.Token.shortUUID()} />}
                    hasMore={!isLastPage}
                    totalCount={activities.length}
                    rowClassName="w-full p-1.5"
                >
                    {activities.map((activity) => (
                        <ActivityTimeline activity={activity} references={activity.references} key={Utils.String.Token.shortUUID()} />
                    ))}
                </InfiniteScroller.Default>
            </Box>
            {countNewRecords > 0 && !isRefreshing && (
                <Button onClick={refreshList} size="sm" className="absolute left-1/2 top-1 z-50 -translate-x-1/2">
                    {t("activity.{count} New Activities", { count: countNewRecords })}
                </Button>
            )}
        </Box>
    );
}

export default ActivityList;
