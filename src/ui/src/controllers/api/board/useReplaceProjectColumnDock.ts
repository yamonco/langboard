import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { ProjectDockSnapshot } from "@/core/models/projectDock";
import applyProjectDockSnapshot from "@/core/helpers/applyProjectDockSnapshot";

interface Form {
    project_uid: string;
    column_uids: string[];
    expected_revision: number;
}

export default function useReplaceProjectColumnDock(options?: TMutationOptions<Form>) {
    const { mutate } = useQueryMutation();
    return mutate(
        ["replace-project-column-dock"],
        async (params: Form) => {
            const url = Utils.String.format(Routing.API.BOARD.COLUMN.REPLACE_DOCK, { uid: params.project_uid });
            const res = await api.put<ProjectDockSnapshot>(
                url,
                { column_uids: params.column_uids, expected_revision: params.expected_revision },
                {
                    env: { interceptToast: options?.interceptToast } as never,
                }
            );
            applyProjectDockSnapshot(params.project_uid, res.data);
            return res.data;
        },
        { ...options, retry: 0 }
    );
}
