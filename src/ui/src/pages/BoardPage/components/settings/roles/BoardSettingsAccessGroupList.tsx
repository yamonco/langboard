import Badge from "@/components/base/Badge";
import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import { User } from "@/core/models";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import { memo, useMemo } from "react";
import { useTranslation } from "react-i18next";

const BoardSettingsAccessGroupList = memo(() => {
    const [t] = useTranslation();
    const { project } = useBoardSettings();
    const accessGroups = project.useField("access_groups") || [];
    const allMembers = project.useForeignFieldArray("all_members");

    const memberNameByUID = useMemo(() => {
        const index = new Map<string, string>();
        for (const member of allMembers) {
            const typedMember = member as User.TModel;
            const label = typedMember.isValidUser()
                ? `${typedMember.firstname} ${typedMember.lastname}`.trim() || typedMember.email
                : typedMember.email;
            index.set(typedMember.uid, label);
        }
        return index;
    }, [allMembers]);

    if (!Array.isArray(accessGroups) || accessGroups.length === 0) {
        return null;
    }

    return (
        <Flex direction="col" gap="3" py="4">
            {accessGroups.map((group) => {
                const memberUIDs = Array.isArray(group.member_uids) ? group.member_uids : [];
                const memberNames = memberUIDs.map((uid) => memberNameByUID.get(uid) || uid);
                return (
                    <Box key={group.uid} className="rounded-lg border p-3">
                        <Flex items="center" justify="between" gap="3">
                            <Flex direction="col" gap="1">
                                <div className="text-sm font-semibold">{group.name}</div>
                                <div className="text-xs text-muted-foreground">{group.description}</div>
                            </Flex>
                            <Badge variant="outline">
                                {t("project.settings.members", { count: Number(group.member_count || memberUIDs.length) })}
                            </Badge>
                        </Flex>
                        <Flex wrap gap="2" mt="3">
                            {memberNames.length > 0 ? (
                                memberNames.map((name) => (
                                    <Badge key={`${group.uid}-${name}`} variant="secondary">
                                        {name}
                                    </Badge>
                                ))
                            ) : (
                                <Badge variant="outline">{t("project.settings.No members")}</Badge>
                            )}
                        </Flex>
                    </Box>
                );
            })}
        </Flex>
    );
});

export default BoardSettingsAccessGroupList;
