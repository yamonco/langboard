export type MemberClassification = "internal" | "external" | "unknown";
export type MemberGroup = MemberClassification | "personal";

export function groupMembers<T extends { uid: string; membership_classification?: MemberClassification }>(members: T[], currentUserUID?: string) {
    const groups = new Map<MemberGroup, T[]>();
    const personal = members.length === 1 && members[0].uid === currentUserUID;
    for (const member of members) {
        const key = personal ? "personal" : (member.membership_classification ?? "unknown");
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key)!.push(member);
    }
    return (["personal", "internal", "external", "unknown"] as MemberGroup[])
        .filter((key) => groups.has(key))
        .map((key) => ({ key, members: groups.get(key)! }));
}
