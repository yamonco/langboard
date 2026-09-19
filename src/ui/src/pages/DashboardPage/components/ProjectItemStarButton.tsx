import Button from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import useToggleStarProject from "@/controllers/api/dashboard/useToggleStarProject";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { memo } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/core/utils/ComponentUtils";
import ContextMenu from "@/components/base/ContextMenu";

export interface IProjectCardStarButtonProps {
    isUpdating: bool;
    setIsUpdating: React.Dispatch<React.SetStateAction<bool>>;
    updateStarredProjects: React.DispatchWithoutAction;
    compact?: bool;
    menuItem?: bool;
}

const ProjectCardStarButton = memo(
    ({ isUpdating, setIsUpdating, updateStarredProjects, compact = false, menuItem = false }: IProjectCardStarButtonProps) => {
        const [t] = useTranslation();
        const { model: project } = ModelRegistry.Project.useContext();
        const { mutate } = useToggleStarProject();
        const starred = project.useField("starred");
        const toggleStar = (event?: React.MouseEvent<HTMLButtonElement>) => {
            if (!project) {
                return;
            }

            event?.preventDefault();
            event?.stopPropagation();

            setIsUpdating(true);

            mutate(
                {
                    uid: project.uid,
                },
                {
                    onSuccess: async () => {
                        updateStarredProjects();
                    },
                    onError: (error) => {
                        const { handle } = setupApiErrorHandler({});

                        handle(error);
                    },
                    onSettled: () => {
                        setIsUpdating(false);
                    },
                }
            );
        };

        if (menuItem) {
            return (
                <ContextMenu.Item disabled={isUpdating} onSelect={() => toggleStar()} className="gap-2">
                    <IconComponent icon="star" size="4" />
                    {t(`dashboard.${starred ? "Unstar this project" : "Star this project"}`)}
                </ContextMenu.Item>
            );
        }

        return (
            <Button
                variant={starred ? "default" : "outline"}
                className={cn(
                    !compact && "absolute right-2.5 top-1 mt-0",
                    compact && "shrink-0 rounded-lg shadow-none",
                    compact &&
                        !starred &&
                        "group-focus-within:opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100"
                )}
                size={compact ? "icon-sm" : "icon"}
                title={t(`dashboard.${starred ? "Unstar this project" : "Star this project"}`)}
                aria-label={t(`dashboard.${starred ? "Unstar this project" : "Star this project"}`)}
                titleSide="bottom"
                onClick={toggleStar}
                disabled={isUpdating}
            >
                {isUpdating ? (
                    <IconComponent icon="loader-circle" size="5" strokeWidth="3" className="animate-spin" />
                ) : (
                    <IconComponent icon="star" />
                )}
            </Button>
        );
    }
);

export default ProjectCardStarButton;
