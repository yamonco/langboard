export enum EEditorType {
    CardDescription = "card-description",
    CardComment = "card-comment",
    CardNewComment = "card-new-comment",
    BotPrompt = "bot-prompt",
    WikiContent = "wiki-content",
}

export type TEditorType = EEditorType;

export enum EEditorCollaborationType {
    AppSettings = "app-settings",
    BoardSettings = "board-settings",
    Card = "card",
    BoardColumnName = "board-column-name",
    BotSchedule = "bot-schedule",
    Wiki = "wiki",
}

export type TEditorCollaborationType = EEditorCollaborationType;
