import { compareProjectActivityPriority, type IActivityPriorityProject } from "./ProjectActivityPriority.ts";

export const PROJECT_RECENT_WORK_LIMIT = 6;
export const PROJECT_QUICK_SWITCHER_EVENT = "langboard:open-project-quick-switcher";

export type TProjectListView = "compact" | "cards";

export interface IProjectDiscoverySections<TProject extends IActivityPriorityProject> {
    all: TProject[];
    favorites: TProject[];
    recent: TProject[];
}

export const buildProjectDiscoverySections = <TProject extends IActivityPriorityProject>(
    projects: readonly TProject[],
    recentLimit = PROJECT_RECENT_WORK_LIMIT
): IProjectDiscoverySections<TProject> => {
    const all = [...projects].sort(compareProjectActivityPriority);
    return {
        all,
        favorites: all.filter((project) => project.starred),
        recent: all.filter((project) => !project.starred).slice(0, recentLimit),
    };
};

export const buildProjectQuickSwitcherSections = <TProject extends IActivityPriorityProject>(projects: readonly TProject[]) => {
    const { all, favorites, recent } = buildProjectDiscoverySections(projects);
    const promotedUIDs = new Set([...favorites, ...recent].map((project) => project.uid));
    return {
        favorites,
        recent,
        other: all.filter((project) => !promotedUIDs.has(project.uid)),
    };
};

export const projectListViewStorageKey = (userUID: string) => `langboard:project-list-view:${userUID}`;

export const parseProjectListView = (value: string | null | undefined): TProjectListView => (value === "cards" ? "cards" : "compact");

export const isProjectQuickSwitcherShortcut = (event: Pick<KeyboardEvent, "altKey" | "ctrlKey" | "key" | "metaKey" | "shiftKey">) =>
    event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;
