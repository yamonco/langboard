export interface ICardCommentAnchor {
    type: "TextQuoteSelector";
    version: 1;
    exact: string;
    prefix: string;
    suffix: string;
    start_block: string;
    end_block: string;
    start_path: number[];
    end_path: number[];
}
