# Secret binding audit

Successful native Dokploy and GlitchTip connection registration and resource selection record a `bound` secret audit fact in the destination transaction. This is distinct from resolving a credential for provider I/O. Failure or rollback of that transaction removes both the destination change and its binding audit fact.

The trusted host operation requires an active destination transaction, an `app_connection` source identifier, current reference authority, active state, and the expected reference revision. It does not read or write vault material or increment the reference revision. Audit pages retain the existing current-reference access checks and never expose raw source identifiers, credentials, or vault paths. The fixed reason is `reference_bound`; labels support English, Korean, Japanese, and Chinese.

The migration expands the existing audit constraint and preserves historical records. Downgrade refuses while binding facts exist. It neither synthesizes old binding events nor backfills prior connections.

This implementation covers native Dokploy and GlitchTip registration and resource selection. GitHub manifest registration, receiver credential binding, wiki secretization/copy producers, authorized source links, and live canary acceptance require their own integration and verification. A binding fact is not evidence of deployment success or workflow approval.
