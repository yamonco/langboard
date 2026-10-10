# Secret binding audit

Successful native Dokploy and GlitchTip connection registration and resource selection, GitHub manifest connection registration, and Dokploy receiver credential configuration record a `bound` secret audit fact in the destination transaction. This is distinct from resolving a credential for provider I/O. Failure or rollback of that transaction removes both the destination change and its binding audit fact.

The trusted host operation requires an active destination transaction, an `app_connection` source identifier, current reference authority, active state, and the expected reference revision. It does not read or write vault material or increment the reference revision. Audit pages retain the existing current-reference access checks and never expose raw source identifiers, credentials, or vault paths. The fixed reason is `reference_bound`; labels support English, Korean, Japanese, and Chinese.

Browser input create and rotation facts correlate through the SHA-256 digest of
their one-use input nonce. The bearer URL nonce and browser proof are never recorded
as audit identifiers. This changes new facts only; existing history is not rewritten.

The migration expands the existing audit constraint and preserves historical records. Downgrade refuses while binding facts exist. It neither synthesizes old binding events nor backfills prior connections.

Audit source links require current native board and card/wiki visibility. App-use policy is independent: disabling apps does not hide a source that the user can still read. Secret ownership alone never grants source access, and deleted sources or revoked membership remain hidden.

Canonical `secret://ref/<uid>` links in the shared Plate editor and static renderer
open the native authenticated per-reference history route. Only a complete canonical
identifier is accepted; aliases, query strings, fragments, and arbitrary Secret
destinations are not history targets. Existing external links retain their confirmation
dialog. The editor stores reference metadata only; a link caption is not a mechanism
for converting or removing plaintext secrets. Dedicated wiki secretization and copy
remain separate work. History access still checks current reference authority on every
request, and readable source links require their own native ACL.

This implementation covers native Dokploy and GlitchTip registration and resource selection, GitHub manifest registration, and Dokploy receiver credential binding. A failed GitHub connection transaction rolls back its binding fact and revokes the independently stored reference; a failed receiver transaction preserves the previous configuration and history. Wiki secretization/copy producers, authorized source links, and live canary acceptance require their own integration and verification. A binding fact is not evidence of deployment success or workflow approval.
