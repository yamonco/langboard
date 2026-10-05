# Vault provider dependencies

The default API and shared package install no longer includes Azure Identity or
Azure Key Vault. Azure deployments must select the `azure-vault` extra explicitly:

```sh
uv sync --locked --no-dev --extra azure-vault
# Shared library consumers:
pip install 'langboard-shared[azure-vault]'
```

For the repository container, choose its provider image target:

```sh
docker build --target with-azure-vault -t langboard-azure .
```

Set `KEY_PROVIDER_TYPE=azure` and configure the existing Azure credentials after
installing this extra. A selected provider with missing dependencies still fails
startup; it does not silently fall back or change encryption/key formats. Provider
selection remains deployment-owned. API users cannot select it through request
arguments. OpenBao/HashiCorp dependencies remain in the default package for the
default production vault. AWS/S3 is optional:

```sh
uv sync --locked --no-dev --extra aws
pip install 'langboard-shared[aws]'
docker build --target with-aws -t langboard-aws .
```

Install `aws` for S3 storage or `KEY_PROVIDER_TYPE=aws`. Local file operations do
not import the AWS SDK. Existing S3 objects retain their `s3` namespace; missing
SDKs do not reinterpret them as local files. S3 operation failures retain the
existing false/None results and upload connection fallback. Selecting the AWS
production vault without its SDK still fails startup. No runtime download occurs.

The `with-document-processing` and `with-cron` targets retain their existing
behavior. Deployments combining Azure with those features should install the
`azure-vault` or `aws` extra in their derived image too; runtime provider selection does
not download packages. No cloud account, organization, domain, or credential is
embedded in the optional package metadata.
