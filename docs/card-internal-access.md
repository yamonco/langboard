# Internal card access policy

`CARD_INTERNAL_ACCESS_MODE` explicitly selects the deployment policy for
`INTERNAL` cards. The default `scim` requires current membership in one of the
configured `MCP_EMPLOYEE_GROUP_IDS` and a matching SCIM identity issuer. Missing
employee configuration or an unknown mode denies internal access.

An existing installation without an employee directory can explicitly select
`project_members` to retain access for active, current board members. Existing
board permissions remain required. This setting does not classify users as
employees and does not change employee status or directory enumeration tools.

Neither policy changes card visibility, grants access across boards, or exposes
another user's `PRIVATE` cards. Configure the same mode on the API and worker.
Before upgrading an installation whose existing cards become `INTERNAL`, verify
its selected policy using an authenticated board member, a nonmember, and a
revoked member. A successful login or an HTTP 200 with an empty list does not
prove the upgrade preserved card access.
