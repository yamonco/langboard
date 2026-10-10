import Subscription from "@/core/server/Subscription";
import { resolveCardAudience } from "@/core/helpers/CardAudience";
import { ESocketTopic } from "@langboard/core/enums";

Subscription.registerValidator(ESocketTopic.BoardCard, async (context) => {
    const allowed = await resolveCardAudience([context.client], [context.topicId]);
    return allowed.has(context.client.user.uid);
});
