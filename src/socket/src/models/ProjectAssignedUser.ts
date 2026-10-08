import BaseModel, { BigIntColumn, TBigIntString } from "@/core/db/BaseModel";
import { getDatetimeType } from "@/core/db/DbType";
import SnowflakeID from "@/core/db/SnowflakeID";
import Card from "@/models/Card";
import { Entity, Column } from "typeorm";

@Entity({ name: "project_assigned_user" })
class ProjectAssignedUser extends BaseModel {
    @BigIntColumn(false)
    public project_id!: TBigIntString;

    @BigIntColumn(false)
    public user_id!: TBigIntString;

    @Column({ type: "boolean" })
    public starred: bool = false;

    @Column({ type: getDatetimeType(), nullable: false })
    public last_viewed_at!: Date;

    public static async isUserRelatedToOtherUser(userId: TBigIntString, otherUserUID: string): Promise<bool> {
        const otherUserId = SnowflakeID.fromShortCode(otherUserUID).toString();
        const result = await ProjectAssignedUser.createQueryBuilder("ua")
            .innerJoin(ProjectAssignedUser, "ub", "ua.project_id = ub.project_id")
            .where("ua.user_id = :userId", { userId })
            .andWhere("ub.user_id = :otherUserId", { otherUserId })
            .limit(1)
            .getCount();

        return result > 0;
    }

    public static async isAssigned(userId: TBigIntString, projectUID: string): Promise<bool> {
        const projectId = SnowflakeID.fromShortCode(projectUID).toString();
        const result = await ProjectAssignedUser.createQueryBuilder("pa")
            .where("pa.project_id = :projectId", { projectId })
            .andWhere("pa.user_id = :userId", { userId })
            .limit(1)
            .getCount();

        return result > 0;
    }

    public static async isAssignedByCard(userId: TBigIntString, cardUID: string): Promise<bool> {
        const cardId = SnowflakeID.fromShortCode(cardUID).toString();
        const result = await ProjectAssignedUser.createQueryBuilder("pa")
            .innerJoin(Card, "c", "c.project_id = pa.project_id")
            .where("pa.user_id = :userId", { userId })
            .andWhere("c.id = :cardId", { cardId })
            .limit(1)
            .getCount();

        return result > 0;
    }
}

export default ProjectAssignedUser;
