import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";
import { INotificationMutation } from "@/core/models/types/notification.type";

type TNotificationCommand = { action: "read" | "delete"; uid: string } | { action: "read_all" | "delete_all" };

const useNotificationCommand = () => {
    const { mutate } = useQueryMutation();

    return mutate<TNotificationCommand, INotificationMutation | null>(["notification-command"], async (command) => {
        switch (command.action) {
            case "read": {
                const res = await api.put(Utils.String.format(Routing.API.NOTIFICATION.READ, { notification_uid: command.uid }));
                return res.data;
            }
            case "read_all": {
                const res = await api.put(Routing.API.NOTIFICATION.READ_ALL);
                return res.data;
            }
            case "delete": {
                const res = await api.delete(Utils.String.format(Routing.API.NOTIFICATION.DELETE, { notification_uid: command.uid }));
                return res.data;
            }
            case "delete_all": {
                const res = await api.delete(Routing.API.NOTIFICATION.DELETE_ALL);
                return res.data;
            }
        }
    });
};

export default useNotificationCommand;
