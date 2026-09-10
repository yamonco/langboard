import { compareProjectActivityPriority, type IProjectActivityPriority as IActivityPriorityProject } from "./ProjectActivityPriority.ts";

export const PROJECT_RECENT_WORK_LIMIT = 6;
export const PROJECT_RELATED_TO_ME_LIMIT = 6;
export const PROJECT_QUICK_SWITCHER_EVENT = "langboard:open-project-quick-switcher";

export type TProjectListView = "compact" | "cards";

export interface IProjectDiscoverySections<TProject extends IActivityPriorityProject> {
    all: TProject[];
    favorites: TProject[];
    related: TProject[];
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
        related: all.filter((project) => !project.starred && project.related_to_current_user).slice(0, PROJECT_RELATED_TO_ME_LIMIT),
        recent: all.filter((project) => !project.starred && !project.related_to_current_user).slice(0, recentLimit),
    };
};

export const buildProjectQuickSwitcherSections = <TProject extends IActivityPriorityProject>(projects: readonly TProject[]) => {
    const { all, favorites, related, recent } = buildProjectDiscoverySections(projects);
    const promotedUIDs = new Set([...favorites, ...related, ...recent].map((project) => project.uid));
    return {
        favorites,
        related,
        recent,
        other: all.filter((project) => !promotedUIDs.has(project.uid)),
    };
};

export const projectListViewStorageKey = (userUID: string) => `langboard:project-list-view:${userUID}`;

export const parseProjectListView = (value: string | null | undefined): TProjectListView => (value === "cards" ? "cards" : "compact");

export const isProjectQuickSwitcherShortcut = (event: Pick<KeyboardEvent, "altKey" | "ctrlKey" | "key" | "metaKey" | "shiftKey">) =>
    event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;

export const projectQuickSwitcherShortcutLabel = (platform: string): string => (/mac|iphone|ipad/i.test(platform) ? "⌘K" : "Ctrl K");
