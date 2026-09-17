import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { api } from "@/core/helpers/Api";
import applyProjectDockSnapshot from "@/core/helpers/applyProjectDockSnapshot";
import { ProjectDockSnapshot } from "@/core/models/projectDock";
import { Project, ProjectColumn } from "@/core/models";
import { getAuthStore } from "@/core/stores/AuthStore";

const inFlight = new WeakMap<Project.TModel, { sessionVersion: number; request: Promise<ProjectDockSnapshot> }>();

export default async function refreshProjectColumnDock(projectUID: string) {
    const project = Project.Model.getModel(projectUID);
    if (!project) return;
    const sessionVersion = getAuthStore().getSessionVersion();
    const isCurrent = () => Project.Model.getModel(projectUID) === project && getAuthStore().getSessionVersion() === sessionVersion;
    const existing = inFlight.get(project);
    if (existing?.sessionVersion === sessionVersion) return existing.request;
    const url = Utils.String.format(Routing.API.BOARD.COLUMN.REPLACE_DOCK, { uid: projectUID });
    const request = api
        .get<ProjectDockSnapshot>(url)
        .then(async (response) => {
            if (!isCurrent()) return response.data;
            applyProjectDockSnapshot(projectUID, response.data);
            const snapshot = project.latestDockSnapshot;
            if (snapshot?.column_uids.some((uid) => !ProjectColumn.Model.getModel(uid))) {
                const columnsURL = Utils.String.format(Routing.API.BOARD.COLUMN.GET_LIST, { uid: projectUID });
                const columnsResponse = await api.get<{ columns: ProjectColumn.IStore[] }>(columnsURL);
                if (isCurrent()) {
                    ProjectColumn.Model.fromArray(columnsResponse.data.columns, true);
                    if (project.latestDockSnapshot) applyProjectDockSnapshot(projectUID, project.latestDockSnapshot);
                }
            }
            return response.data;
        })
        .finally(() => {
            if (inFlight.get(project)?.request === request) inFlight.delete(project);
        });
    inFlight.set(project, { sessionVersion, request });
    return request;
}
