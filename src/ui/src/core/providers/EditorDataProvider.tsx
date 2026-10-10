/* eslint-disable @typescript-eslint/no-explicit-any */
import { createContext, useCallback, useContext, useMemo } from "react";
import { AuthUser } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import { EEditorCollaborationType, EEditorType, Routing } from "@langboard/core/constants";
import type { TEditorType } from "@langboard/core/constants";
import { TUserLikeModel } from "@/core/models/ModelRegistry";
import { TInternalLinkableModel, TInternalLinkElement } from "@/components/Editor/plugins/customs/internal-link/InternalLinkPlugin";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";

export type TEditorDataProviderEditorType = "view" | TEditorType;

export interface IEditorDataContext {
    currentUser: AuthUser.TModel;
    mentionables: TUserLikeModel[];
    linkables: TInternalLinkableModel[];
    editorType: TEditorDataProviderEditorType;
    form?: any;
    documentID?: string;
    socketEvents?: ReturnType<typeof createEditorSocketEvents>;
    chatEventKey?: string;
    copilotEventKey?: string;
    uploadPath?: string;
    uploadedCallback?: (respones: any) => void;
    createInternalLink: (type: TInternalLinkElement["internalType"], uid: string) => () => void;
}

interface IBaseEditorDataProviderProps {
    currentUser: AuthUser.TModel;
    mentionables: TUserLikeModel[];
    linkables?: TInternalLinkableModel[];
    editorType: TEditorDataProviderEditorType;
    form?: any;
    uploadedCallback?: (respones: any) => void;
    children: React.ReactNode;
}

interface IViewEditorDataProviderProps extends IBaseEditorDataProviderProps {
    editorType: "view";
    form?: {
        project_uid?: string;
    };
}

interface ICardDescriptionEditorDataProviderProps extends IBaseEditorDataProviderProps {
    editorType: typeof EEditorType.CardDescription;
    form: {
        project_uid: string;
        card_uid: string;
    };
}

interface ICardCommentEditorDataProviderProps extends IBaseEditorDataProviderProps {
    editorType: typeof EEditorType.CardComment;
    form: {
        project_uid: string;
        card_uid: string;
        comment_uid: string;
    };
}

interface ICardNewCommentEditorDataProviderProps extends IBaseEditorDataProviderProps {
    editorType: typeof EEditorType.CardNewComment;
    form: {
        project_uid: string;
        card_uid: string;
    };
}

interface IBotPromptEditorDataProviderProps extends IBaseEditorDataProviderProps {
    editorType: typeof EEditorType.BotPrompt;
    form: {
        uid: string | number;
        section: string | number;
    };
}

interface IWikiContentEditorDataProviderProps extends IBaseEditorDataProviderProps {
    editorType: typeof EEditorType.WikiContent;
    form: {
        project_uid: string;
        wiki_uid: string;
    };
}

export type TEditorDataProviderProps =
    | IViewEditorDataProviderProps
    | ICardDescriptionEditorDataProviderProps
    | ICardCommentEditorDataProviderProps
    | ICardNewCommentEditorDataProviderProps
    | IBotPromptEditorDataProviderProps
    | IWikiContentEditorDataProviderProps;

const initialContext = {
    currentUser: {} as AuthUser.TModel,
    mentionables: [],
    linkables: [],
    editorType: "view" as TEditorDataProviderEditorType,
    createInternalLink: () => () => {},
};

const EditorDataContext = createContext<IEditorDataContext>(initialContext);

const createEditorSocketEvents = (baseEvent: string) => ({
    chatEvents: {
        abort: `${baseEvent}:editor:chat:abort`,
        send: `${baseEvent}:editor:chat:send`,
        stream: `${baseEvent}:editor:chat:stream`,
    },
    copilotEvents: {
        abort: `${baseEvent}:editor:copilot:abort`,
        send: `${baseEvent}:editor:copilot:send`,
        receive: `${baseEvent}:editor:copilot:receive`,
    },
});

export const EditorDataProvider = ({
    currentUser,
    mentionables,
    linkables = [],
    editorType,
    form,
    uploadedCallback,
    children,
}: TEditorDataProviderProps): React.ReactNode => {
    const navigate = usePageNavigateRef();
    const [baseSocketEvent, documentID, chatEventKey, copilotEventKey, uploadPath] = useMemo(() => {
        switch (editorType) {
            case EEditorType.CardDescription: {
                const cardForm = form as ICardDescriptionEditorDataProviderProps["form"];
                return [
                    "board:card",
                    Utils.String.createEditorCollaborationDocumentID({
                        collaborationType: EEditorCollaborationType.Card,
                        uid: cardForm.card_uid,
                        section: "description",
                    }),
                    `${editorType}-chat-${cardForm.card_uid}`,
                    `${editorType}-copilot-${cardForm.card_uid}`,
                    Utils.String.format(Routing.API.BOARD.CARD.ATTACHMENT.UPLOAD, { uid: cardForm.project_uid, card_uid: cardForm.card_uid }),
                ];
            }
            case EEditorType.CardComment: {
                const commentForm = form as ICardCommentEditorDataProviderProps["form"];
                return [
                    "board:card",
                    Utils.String.createEditorCollaborationDocumentID({
                        collaborationType: EEditorCollaborationType.Card,
                        uid: commentForm.card_uid,
                        section: `comment-${commentForm.comment_uid}`,
                    }),
                    `${editorType}-chat-${commentForm.comment_uid}`,
                    `${editorType}-copilot-${commentForm.comment_uid}`,
                    Utils.String.format(Routing.API.BOARD.CARD.ATTACHMENT.UPLOAD, { uid: commentForm.project_uid, card_uid: commentForm.card_uid }),
                ];
            }
            case EEditorType.CardNewComment: {
                const newCommentForm = form as ICardNewCommentEditorDataProviderProps["form"];
                return [
                    "board:card",
                    undefined,
                    `${editorType}-chat-${newCommentForm.card_uid}`,
                    `${editorType}-copilot-${newCommentForm.card_uid}`,
                    Utils.String.format(Routing.API.BOARD.CARD.ATTACHMENT.UPLOAD, {
                        uid: newCommentForm.project_uid,
                        card_uid: newCommentForm.card_uid,
                    }),
                ];
            }
            case EEditorType.BotPrompt: {
                const botPromptForm = form as IBotPromptEditorDataProviderProps["form"];
                return [
                    undefined,
                    Utils.String.createEditorCollaborationDocumentID({
                        collaborationType: EEditorCollaborationType.AppSettings,
                        uid: botPromptForm.uid,
                        section: botPromptForm.section,
                    }),
                    undefined,
                    undefined,
                    undefined,
                ];
            }
            case EEditorType.WikiContent: {
                const wikiForm = form as IWikiContentEditorDataProviderProps["form"];
                return [
                    "board:wiki",
                    Utils.String.createEditorCollaborationDocumentID({
                        collaborationType: EEditorCollaborationType.Wiki,
                        uid: wikiForm.wiki_uid,
                        section: "content",
                    }),
                    `${editorType}-chat-${wikiForm.wiki_uid}`,
                    `${editorType}-copilot-${wikiForm.wiki_uid}`,
                    Utils.String.format(Routing.API.BOARD.WIKI.UPLOAD, { uid: wikiForm.project_uid, wiki_uid: wikiForm.wiki_uid }),
                ];
            }
            default:
                return [undefined, undefined, undefined, undefined, undefined];
        }
    }, [editorType, form]);
    const socketEvents = useMemo(() => {
        if (baseSocketEvent) {
            return createEditorSocketEvents(baseSocketEvent);
        } else {
            return undefined;
        }
    }, [baseSocketEvent]);
    const createInternalLink = useCallback(
        (type: TInternalLinkElement["internalType"], uid: string) => () => {
            const boardForm = form as { project_uid?: string } | undefined;

            switch (type) {
                case "card":
                    if (!boardForm?.project_uid) {
                        return;
                    }

                    navigate(ROUTES.BOARD.CARD(boardForm.project_uid, uid));
                    break;
                case "project_wiki":
                    if (!boardForm?.project_uid) {
                        return;
                    }

                    navigate(ROUTES.BOARD.WIKI_PAGE(boardForm.project_uid, uid));
                    break;
            }
        },
        [form]
    );

    const contextValue = useMemo(
        () => ({
            currentUser,
            mentionables,
            linkables,
            editorType,
            form,
            documentID,
            socketEvents,
            chatEventKey,
            copilotEventKey,
            uploadPath,
            uploadedCallback,
            createInternalLink,
        }),
        [
            currentUser,
            mentionables,
            linkables,
            editorType,
            form,
            documentID,
            socketEvents,
            chatEventKey,
            copilotEventKey,
            uploadPath,
            uploadedCallback,
            createInternalLink,
        ]
    );

    return <EditorDataContext.Provider value={contextValue}>{children}</EditorDataContext.Provider>;
};

export const useEditorData = () => {
    const context = useContext(EditorDataContext);
    if (!context) {
        throw new Error("useEditorData must be used within a EditorDataProvider");
    }
    return context;
};
