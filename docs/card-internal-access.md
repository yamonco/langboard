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

For customer collaboration, do not use `project_members`: it deliberately grants
internal access to every current board member. If an identity authority is
restricted to internal collaborators, explicitly select `oidc_issuers` and set
`CARD_INTERNAL_OIDC_ISSUERS` to its exact issuer URL. This mode requires a current
OIDC identity link with a nonempty subject and still requires an active account
and current board membership. An absent or different identity authority grants
no internal access. Never select a public or mixed employee/customer issuer.

This policy describes collaboration access, not employment. Customer-visible
cards must be explicitly shared through the human UI; selecting an identity
authority does not convert existing internal cards to shared cards.

## Global SCIM employee selection

Installation administrators can select employee groups in Settings → Users.
The selection is persisted in the shared database and used by both card access
and the native employee tools. Selecting any synchronized group qualifies its
active members; group display names are informational. Matching uses Langboard's
SCIM resource ID, so identity providers that omit `externalId` are supported.
The configured SCIM issuer must match the user's current SCIM identity link.
Changing the issuer does not reuse the previous employee selection. An explicit
empty selection denies employee access; it never restores the OIDC fallback.
Legacy `MCP_EMPLOYEE_GROUP_IDS` remains a fallback until the first UI save.

The current native SCIM deployment has one configured provisioning authority.
This works with any compliant SCIM 2.0 provider; simultaneous independent
provisioning authorities are not implied by this setting.

Existing card visibility is not changed when membership settings are saved.
A human-requested, one-time deployment migration may share existing INTERNAL
cards on mixed external-member boards. It must preserve PRIVATE cards and keep
a private before-state receipt. No periodic reconciliation is required.
