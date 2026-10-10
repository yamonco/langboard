import { useEffect, useId } from "react";
import { useSocketOutsideProvider } from "@/core/providers/SocketProvider";
import { SocketEvents } from "@langboard/core/constants";
import { acquireProjectWorkload } from "./projectWorkloadSubscriptions";
import { isAxiosError } from "axios";
import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Project, ProjectColumn } from "@/core/models";
import { deleteProjectModel } from "@/core/helpers/ModelHelper";
import { EHttpStatus, ESocketTopic } from "@langboard/core/enums";

export interface IGetProjectsResponse {
    projects: Project.TModel[];
    columns: ProjectColumn.TModel[];
}

const useGetProjects = (options?: TQueryOptions<unknown, IGetProjectsResponse>) => {
    const { query, queryClient } = useQueryMutation();
    const subscriber = useId();

    const getProjects = async ({ signal }: { signal: AbortSignal }): Promise<IGetProjectsResponse | undefined> => {
        try {
            const res = await api.get(Routing.API.DASHBOARD.PROJECTS, {
                signal,
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            });

            signal.throwIfAborted();
            const projects = Project.Model.fromArray(res.data.projects, true);
            const columns = ProjectColumn.Model.fromArray(res.data.columns, true);
            const projectUIDs = new Set<string>(projects.map((project) => project.uid));

            const columnUIDs = new Set(columns.map((column) => column.uid));
            ProjectColumn.Model.getModels((column) => projectUIDs.has(column.project_uid) && !columnUIDs.has(column.uid)).forEach((column) =>
                ProjectColumn.Model.deleteModel(column.uid)
            );

            Project.Model.getModels((model) => !projectUIDs.has(model.uid)).forEach((model) => {
                deleteProjectModel(ESocketTopic.Dashboard, model.uid);
            });

            return { projects, columns };
        } catch (e) {
            if (!isAxiosError(e)) {
                throw e;
            }

            if (e.status === EHttpStatus.HTTP_404_NOT_FOUND) {
                return undefined;
            }

            throw e;
        }
    };

    const result = query(["get-dashboard-projects"], getProjects, {
        ...options,
        retry: 0,
        staleTime: options?.staleTime ?? 30_000,
        refetchInterval: Infinity,
        refetchOnWindowFocus: options?.refetchOnWindowFocus ?? false,
    });
    const projectUIDs =
        result.data?.projects
            .map((project) => project.uid)
            .sort()
            .join(",") ?? "";
    useEffect(() => {
        const socket = useSocketOutsideProvider();
        return acquireProjectWorkload(queryClient, projectUIDs.split(",").filter(Boolean), {
            subscribe: (uids, onSubscribed) => socket.subscribe(ESocketTopic.Dashboard, uids, onSubscribed),
            unsubscribe: (uids) => socket.unsubscribe(ESocketTopic.Dashboard, uids),
            listen: (uid, callback) => {
                const props = {
                    topic: ESocketTopic.Dashboard as const,
                    topicId: uid,
                    event: SocketEvents.SERVER.DASHBOARD.PROJECT.ACTIVITY_RECORDED.replace("{uid}", uid),
                    eventKey: `project-workload-${subscriber}-${uid}`,
                    callback,
                };
                socket.on(props);
                return () => socket.off(props);
            },
            listenOpen: (callback) => {
                const props = { event: "open" as const, eventKey: `project-workload-open-${subscriber}`, callback };
                socket.on(props);
                return () => socket.off(props);
            },
        });
    }, [projectUIDs, queryClient, subscriber]);
    return result;
};

export default useGetProjects;
