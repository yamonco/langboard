import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";

interface IWikiSearchResponse {
    items: { wiki_uid: string; title: string; snippet?: string }[];
    next_cursor: string | null;
}

export default function useSearchWikis(projectUID: string | undefined, queryText: string, enabled: boolean) {
    const { query } = useQueryMutation();
    return query<IWikiSearchResponse>(
        ["wiki-search", projectUID, queryText],
        async () => {
            const url = `${Utils.String.format(Routing.API.BOARD.WIKI.GET_ALL, { uid: projectUID })}/search`;
            const response = await api.get(url, { params: { query: queryText } });
            return response.data;
        },
        { enabled: enabled && !!projectUID && queryText.length >= 2, retry: 0, refetchOnWindowFocus: false }
    );
}
