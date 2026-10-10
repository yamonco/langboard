import { Project, ProjectColumn } from "@/core/models";
import { applyProjectDockProjection, ProjectDockSnapshot, retainProjectDockSnapshot } from "@/core/models/projectDock";

export default function applyProjectDockSnapshot(projectUID: string, snapshot: ProjectDockSnapshot) {
    const project = Project.Model.getModel(projectUID);
    if (!project) return false;
    const retained = retainProjectDockSnapshot(project.dock_revision, snapshot);
    if (!retained) return false;
    project.latestDockSnapshot = retained;
    project.dock_revision = retained.revision;
    const columns = ProjectColumn.Model.getModels((column) => column.project_uid === projectUID);
    return applyProjectDockProjection(project, columns, retained);
}
