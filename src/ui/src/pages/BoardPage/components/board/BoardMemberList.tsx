import MultiSelectAssignee, { IFormProps, TSaveHandler } from "@/components/MultiSelectAssignee";
import Toast from "@/components/base/Toast";
import { EMAIL_REGEX } from "@/constants";
import useUpdateProjectAssignedUsers from "@/controllers/api/board/useUpdateProjectAssignedUsers";
import { api } from "@/core/helpers/Api";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { BotModel, User } from "@/core/models";
import { TUserLikeModel } from "@/core/models/ModelRegistry";
import { ProjectRole } from "@/core/models/roles";
import { useBoard } from "@/core/providers/BoardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import BoardMemberDrag from "@/pages/BoardPage/components/board/BoardMemberDrag";

export interface IBoardMemberListProps {
    isSelectCardView: bool;
}

const BoardMemberList = memo(({ isSelectCardView }: IBoardMemberListProps) => {
    const [t] = useTranslation();
    const { project, currentUser, hasRoleAction, canDragCards } = useBoard();
    const canEdit = hasRoleAction(ProjectRole.EAction.Update);
    const ownerUID = project.useField("owner_uid");
    const allMemebers = project.useForeignFieldArray("all_members");
    const invitedMemberUIDs = project.useField("invited_member_uids");
    const currentUserUID = currentUser.useField("uid");
    const canEditMembers = canEdit || ownerUID === currentUserUID;
    const groups = currentUser.useForeignFieldArray("user_groups");
    const [candidateSearchInput, setCandidateSearchInput] = useState("");
    const [candidateSearchQuery, setCandidateSearchQuery] = useState("");
    const [memberCandidates, setMemberCandidates] = useState<User.TModel[]>([]);
    const directCandidateUIDsRef = useRef(new Set<string>());
    const visibleMembers = useMemo(() => allMemebers.filter((model) => !model.isDeletedUser()), [allMemebers]);
    const allSelectables = useMemo(() => {
        const userMap = new Map<string, User.TModel>();

        for (const user of [...visibleMembers, ...memberCandidates]) {
            if (!user.isValidUser() && !user.isPresentableUnknownUser()) {
                continue;
            }

            if (user.uid === ownerUID || user.uid === currentUserUID) {
                continue;
            }

            userMap.set(user.uid, user);
        }

        return [...userMap.values()];
    }, [currentUserUID, memberCandidates, ownerUID, visibleMembers]);
    const showableAssignees = useMemo(
        () => visibleMembers.filter((model) => model.isValidUser() && !invitedMemberUIDs.includes(model.uid)),
        [invitedMemberUIDs, visibleMembers]
    );
    const selectedAssignees = useMemo(() => visibleMembers.filter((model) => model.uid !== ownerUID), [ownerUID, visibleMembers]);
    const hiddenCurrentUserAssignee = useMemo(
        () => selectedAssignees.find((item) => item.uid === currentUserUID),
        [currentUserUID, selectedAssignees]
    );
    const visibleSelectedAssignees = useMemo(
        () => selectedAssignees.filter((item) => item.uid !== currentUserUID),
        [currentUserUID, selectedAssignees]
    );
    const { mutateAsync: updateProjectAssignedUsersMutateAsync } = useUpdateProjectAssignedUsers({ interceptToast: true });
    const memberInvitePlaceholder = t("myAccount.Add an email...");
    const isCandidateSearchPlaceholder = useCallback(
        (search: string) => {
            const trimmedSearch = search.trim();

            return trimmedSearch === memberInvitePlaceholder || trimmedSearch === "Add an email...";
        },
        [memberInvitePlaceholder]
    );
    const normalizeCandidateSearch = useCallback(
        (search: string) => {
            return isCandidateSearchPlaceholder(search) ? "" : search;
        },
        [isCandidateSearchPlaceholder]
    );
    const updateCandidateSearchInput = useCallback(
        (search: string) => {
            setCandidateSearchInput(normalizeCandidateSearch(search));
        },
        [normalizeCandidateSearch]
    );

    useEffect(() => {
        const timeout = window.setTimeout(() => {
            setCandidateSearchQuery(normalizeCandidateSearch(candidateSearchInput).trim());
        }, 250);

        return () => {
            window.clearTimeout(timeout);
        };
    }, [candidateSearchInput, normalizeCandidateSearch]);

    useEffect(() => {
        const updateSearchFromEditor = () => {
            window.setTimeout(() => {
                const textbox = document.querySelector<HTMLElement>("[data-member-invite-popover='true'] [role='textbox']");
                const search = textbox?.textContent ?? "";
                updateCandidateSearchInput(search);
            }, 0);
        };
        let observer: MutationObserver | undefined;
        const observerInterval = window.setInterval(() => {
            const textbox = document.querySelector<HTMLElement>("[data-member-invite-popover='true'] [role='textbox']");
            updateSearchFromEditor();

            if (!textbox || observer) {
                return;
            }

            observer = new MutationObserver(updateSearchFromEditor);
            observer.observe(textbox, {
                childList: true,
                characterData: true,
                subtree: true,
            });
            updateSearchFromEditor();
        }, 50);

        document.addEventListener("input", updateSearchFromEditor, true);
        document.addEventListener("keyup", updateSearchFromEditor, true);
        document.addEventListener("compositionend", updateSearchFromEditor, true);

        return () => {
            observer?.disconnect();
            window.clearInterval(observerInterval);
            document.removeEventListener("input", updateSearchFromEditor, true);
            document.removeEventListener("keyup", updateSearchFromEditor, true);
            document.removeEventListener("compositionend", updateSearchFromEditor, true);
        };
    }, [updateCandidateSearchInput]);

    useEffect(() => {
        if (!canEditMembers || candidateSearchQuery.length < 2 || isCandidateSearchPlaceholder(candidateSearchQuery)) {
            setMemberCandidates([]);
            return;
        }

        let cancelled = false;
        const url = Utils.String.format(Routing.API.BOARD.MEMBER_CANDIDATES, {
            uid: project.uid,
        });

        api.get(url, {
            params: {
                query: candidateSearchQuery,
            },
        })
            .then((res) => {
                if (!cancelled) {
                    const candidates = User.Model.fromArray(res.data.users ?? [], true);
                    candidates.forEach((candidate) => directCandidateUIDsRef.current.add(candidate.uid));
                    setMemberCandidates(candidates);
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setMemberCandidates([]);
                }
            });

        return () => {
            cancelled = true;
        };
    }, [canEditMembers, candidateSearchQuery, isCandidateSearchPlaceholder, project]);

    const save = (items: (string | User.TModel)[]) => {
        const mergedItems = hiddenCurrentUserAssignee ? [...items, hiddenCurrentUserAssignee] : items;
        const directCandidateUIDs = directCandidateUIDsRef.current;
        const promise = updateProjectAssignedUsersMutateAsync({
            uid: project.uid,
            emails: mergedItems.flatMap((item) => {
                if (Utils.Type.isString(item)) {
                    return [item];
                }
                return !directCandidateUIDs.has(item.uid) && "email" in item && Utils.Type.isString(item.email) ? [item.email] : [];
            }),
            member_uids: mergedItems.flatMap((item) =>
                !Utils.Type.isString(item) && directCandidateUIDs.has(item.uid) ? [item.uid] : []
            ),
        });

        Toast.Add.promise(promise, {
            loading: t("common.Updating..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t("successes.Assigned members updated and invited new users successfully.");
            },
        });

        return promise;
    };

    return (
        <MultiSelectAssignee.Popover
            popoverButtonProps={{
                size: "icon",
                className: cn("size-8 xs:size-10", isSelectCardView ? "hidden" : ""),
                title: t("project.Assign members"),
            }}
            popoverContentProps={
                {
                    className: cn(
                        "max-w-[calc(100vw_-_theme(spacing.20))]",
                        "sm:max-w-[calc(theme(screens.sm)_-_theme(spacing.60))]",
                        "lg:max-w-[calc(theme(screens.md)_-_theme(spacing.60))]",
                        "min-w-[min(theme(spacing.20),100%)]"
                    ),
                    align: "start",
                    "data-member-invite-popover": "true",
                } as Record<string, unknown>
            }
            userAvatarListProps={{
                maxVisible: 6,
                size: { initial: "sm", xs: "default" },
                spacing: "3",
                listAlign: "start",
                renderAvatar: canDragCards
                    ? (member, avatar) => (
                          <BoardMemberDrag projectUID={project.uid} memberUID={member.uid}>
                              {avatar}
                          </BoardMemberDrag>
                      )
                    : undefined,
            }}
            tagContentProps={{
                scope: {
                    projectUID: project.uid,
                },
            }}
            renderSelectableItem={
                ((item: TUserLikeModel) => {
                    if (item.MODEL_NAME === BotModel.Model.MODEL_NAME) {
                        item = item as BotModel.TModel;
                        return `${item.name} (${item.bot_uname})`;
                    }

                    item = item as User.TModel;
                    const isInvited = item.isPresentableUnknownUser() || invitedMemberUIDs.includes(item.uid);
                    const invitedText = isInvited ? ` (${t("project.invited")})` : "";
                    return item.isValidUser() ? `${item.firstname} ${item.lastname}${invitedText}`.trim() : `${item.email} ${invitedText}`;
                }) as IFormProps["renderSelectableItem"]
            }
            addIconSize="6"
            allSelectables={allSelectables}
            showableAssignees={showableAssignees}
            selectedAssignees={visibleSelectedAssignees}
            originalAssignees={visibleSelectedAssignees}
            createSearchKeywords={(item: string | TUserLikeModel) => {
                if (Utils.Type.isString(item)) {
                    return [item];
                }

                if (item.MODEL_NAME === BotModel.Model.MODEL_NAME) {
                    return [];
                }

                item = item as User.TModel;
                if (item.isValidUser()) {
                    return [item.email, item.firstname, item.lastname];
                } else {
                    return [item.email, t("project.invited")];
                }
            }}
            createLabel={(item: string | TUserLikeModel) => {
                if (Utils.Type.isString(item)) {
                    return item;
                }

                if (item.MODEL_NAME === BotModel.Model.MODEL_NAME) {
                    item = item as BotModel.TModel;
                    return `${item.name} (${item.bot_uname})`;
                }

                item = item as User.TModel;
                const isInvited = item.isPresentableUnknownUser() || invitedMemberUIDs.includes(item.uid);
                const invitedText = isInvited ? ` (${t("project.invited")})` : "";
                if (item.isValidUser()) {
                    return `${item.firstname} ${item.lastname}${invitedText}`.trim();
                } else {
                    return `${item.email} ${invitedText}`;
                }
            }}
            onSearchChange={updateCandidateSearchInput}
            placeholder={memberInvitePlaceholder}
            canAddNew
            validateNewItem={(value) => !!value && EMAIL_REGEX.test(value)}
            saveOnChange
            save={save as TSaveHandler}
            withUserGroups
            groups={groups}
            canEdit={canEditMembers}
        />
    );
});
BoardMemberList.displayName = "Board.MemberList";

export default BoardMemberList;
