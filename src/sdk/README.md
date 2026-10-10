# Independently versioned SDK consumption

SDK source and package tests live in [langboard-sdk](https://github.com/yamonco/langboard-sdk).
This host consumes the same reviewed npm tarball and Python wheel as external apps.
`vendor/provenance.json` records package versions and SHA256 digests. The UI lockfile
pins the npm artifact; both Python lockfiles pin the wheel hash. This snapshot is
not a public npm/PyPI registry publication.

Update the SDK in its repository, run its standalone checks, build artifacts, then
update this directory and the host lockfiles in a reviewed change. Never edit the
package bytes here or restore parallel SDK source implementations. Native host
integration tests remain in this repository because current authentication,
permissions, consent and resource projections are owned by the host.

Panel protocol v1 and package semver are distinct. Existing lifecycle-only panels
remain supported. `signals.list` additionally needs the native panel read bridge,
explicit `signals.read` board consent and current provider resource authority.
An older host without the bridge returns an unavailable error; no permission or
provider operation is inferred from SDK installation.

Python SDK 0.2.1 adds `GlitchTipManager.disable_read` and
`DokployManager.disable_read`. The host and shared Python manifests/lockfiles pin
the same wheel SHA256 recorded in provenance. Integration tests import that wheel
directly and exercise authenticated native read, revocation, denied refresh and
explicit re-consent with persistent observations. No SDK source-directory import
or editable installation is used. The panel package remains 0.2.0/protocol v1.
This local package update is not a registry publication or deployed host claim.
