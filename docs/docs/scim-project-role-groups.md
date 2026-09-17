# SCIM project role groups

Langboard can project SCIM group membership onto an existing project's access roles. This keeps authentication in OIDC while allowing a directory service to remain authoritative for employee access.

## Identity boundary

- A SCIM user's `externalId` is the stable identity key. Email is mutable profile data.
- `POST /scim/v2/Users` does not attach a new `externalId` to an existing account merely because its email matches. It returns `409 Conflict` instead.
- An administrator can explicitly link a pre-existing account with `PUT /scim/v2/Users/{userUid}` and the intended `externalId`.
- A linked `externalId` cannot later be reassigned or replaced through an ordinary profile update.

## Group contract

Create ordinary SCIM groups as usual, but reserve this `externalId` form for a project role group:

```text
project-role:{projectUid}:{role}
```

Supported roles are:

| Role | Effective access |
| --- | --- |
| `viewer` | Read |
| `contributor` | Read, create cards, and update cards |
| `owner` | All project actions |

If a user appears in more than one role group for the same project, the highest role wins deterministically: `owner`, then `contributor`, then `viewer`.

Once any project role group is written, its combined group membership is authoritative for SCIM-managed users in that project. Langboard immediately reconciles the project membership and role records, then reads them back before returning success.

- Removing a SCIM-managed user from every role group removes that user's project access.
- Deactivating or deleting a SCIM user removes the user from role groups and revokes projected project access.
- Non-SCIM local users and guests are not removed by reconciliation.
- The intrinsic project owner is never demoted or removed by SCIM.
- Project role groups reject users that are not linked to the configured `SCIM_ISSUER`.

Changing or deleting a role group's binding reconciles both the former and current projects. A failed readback returns `503 Service Unavailable`; the stored group remains the desired state, so the same SCIM write can be retried safely.
