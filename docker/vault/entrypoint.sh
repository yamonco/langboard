#!/bin/bash

set -e

echo "=========================================="
echo "ENTRYPOINT.SH STARTED"
echo "ROOT_TOKEN: ${ROOT_TOKEN:+SET}"
echo "=========================================="

if [ -s /openbao/vault-secret.json ] && [ ! -s /openbao/file/core/_seal-config ]; then
    echo "Existing OpenBao credentials found, but the data volume is empty or incomplete. Restore the Vault data before starting." >&2
    exit 1
fi

# Start OpenBao server in background for initialization/check
echo "🔧 Starting OpenBao server..."
docker-entrypoint.sh server &
SERVER_PID=$!

# Wait for server to be ready
echo "⏳ Waiting for OpenBao to start..."
sleep 15

export BAO_ADDR="http://127.0.0.1:8200"
VAULT_URL="$BAO_ADDR"
ROLE_NAME="${PROJECT_NAME}-role"
CREDENTIALS_FILE="/openbao/.vault-credentials"

echo "⏳ Checking OpenBao initialization status..."

# Check if vault-secret.json already exists from previous initialization
if [ -f /openbao/vault-secret.json ] && [ -s /openbao/vault-secret.json ]; then
    echo "📋 Found existing vault-secret.json. Loading credentials..."
    UNSEAL_KEY=$(cat /openbao/vault-secret.json | grep -o '"keys_base64":\[[^]]*\]' | sed 's/"keys_base64":\[\([^]]*\)\]/\1/' | cut -d',' -f1 | tr -d ' "')
    ROOT_TOKEN=$(cat /openbao/vault-secret.json | grep -o '"root_token":"[^"]*"' | cut -d'"' -f4)
    export BAO_TOKEN="$ROOT_TOKEN"
    echo "✅ Loaded existing credentials"
else
    # Check if OpenBao is initialized
    INIT_STATUS=$(wget -qO- "http://127.0.0.1:8200/v1/sys/init" 2>/dev/null | grep -o '"initialized":[^,]*' | cut -d':' -f2)

    if [ "$INIT_STATUS" != "true" ]; then
        echo "🔧 OpenBao not initialized. Initializing..."

        # Initialize OpenBao using HTTP API
        wget -qO- --post-data='{"secret_shares":1,"secret_threshold":1}' \
            --header='Content-Type: application/json' \
            "$BAO_ADDR/v1/sys/init" > /openbao/vault-secret.json

        echo "✅ OpenBao initialized"

        # Extract unseal key and root token from JSON response
        UNSEAL_KEY=$(cat /openbao/vault-secret.json | grep -o '"keys_base64":\[[^]]*\]' | sed 's/"keys_base64":\[\([^]]*\)\]/\1/' | cut -d',' -f1 | tr -d ' "')
        ROOT_TOKEN=$(cat /openbao/vault-secret.json | grep -o '"root_token":"[^"]*"' | cut -d'"' -f4)

        # Unseal OpenBao using HTTP API
        echo "🔧 Unsealing OpenBao..."
        wget -qO- --post-data="{\"key\":\"$UNSEAL_KEY\"}" \
            --header='Content-Type: application/json' \
            "$BAO_ADDR/v1/sys/unseal" >/dev/null
        echo "✅ OpenBao unsealed"

        export BAO_TOKEN="$ROOT_TOKEN"
    else
        echo "✅ OpenBao already initialized, but no vault-secret.json found"
        echo "❌ Cannot proceed without unseal key. Please clear volumes and restart."
        kill $SERVER_PID 2>/dev/null
        exit 1
    fi
fi

# Check if sealed and unseal if needed
SEALED=$(wget -qO- "http://127.0.0.1:8200/v1/sys/seal-status" 2>/dev/null | grep -o '"sealed":[^,]*' | cut -d':' -f2)
if [ "$SEALED" = "true" ]; then
    echo "🔧 OpenBao is sealed. Auto-unsealing..."
    if [ -f /openbao/vault-secret.json ]; then
        UNSEAL_KEY=$(cat /openbao/vault-secret.json | grep -o '"keys_base64":\[[^]]*\]' | sed 's/"keys_base64":\[\([^]]*\)\]/\1/' | cut -d',' -f1 | tr -d ' "')
        wget -qO- --post-data="{\"key\":\"$UNSEAL_KEY\"}" \
            --header='Content-Type: application/json' \
            "$BAO_ADDR/v1/sys/unseal" >/dev/null
        echo "✅ OpenBao unsealed"

        ROOT_TOKEN=$(cat /openbao/vault-secret.json | grep -o '"root_token":"[^"]*"' | cut -d'"' -f4)
        export BAO_TOKEN="$ROOT_TOKEN"
    else
        echo "❌ Cannot find unseal key. Please reinitialize."
        kill $SERVER_PID 2>/dev/null
        exit 1
    fi
fi

# Check if credentials file already exists
if [ -f "$CREDENTIALS_FILE" ] && [ -s "$CREDENTIALS_FILE" ]; then
    echo "✅ Credentials file already exists. Skipping configuration."
    echo ""
    echo "🔄 OpenBao server is already running (PID: $SERVER_PID)"
    wait $SERVER_PID
fi

# Check if ROOT_TOKEN is set before proceeding with configuration
if [ -z "$ROOT_TOKEN" ]; then
    echo "⚠️  ROOT_TOKEN not set. Skipping configuration. Keeping server running..."
    wait $SERVER_PID
fi

# Enable AppRole auth method
echo "🔧 Configuring AppRole authentication..."
if ! bao auth list 2>/dev/null | grep -q "approle/"; then
    bao auth enable approle
    echo "✅ AppRole enabled"
else
    echo "✅ AppRole already enabled"
fi

# Create policy for apikeys
echo "🔧 Creating policy for apikeys..."
cat > /tmp/apikeys-policy.hcl << 'EOF'
path "apikeys/data/*" {
  capabilities = ["create", "update", "read"]
}

path "apikeys/metadata/*" {
  capabilities = ["create", "update", "delete", "list"]
}

path "apikeys/delete/*" {
  capabilities = ["update"]
}
EOF
bao policy write apikeys-policy /tmp/apikeys-policy.hcl
echo "✅ Policy created"

# Create or update the role
echo "🔧 Creating/updating AppRole: $ROLE_NAME"
bao write auth/approle/role/$ROLE_NAME token_policies=apikeys-policy
echo "✅ Role created/updated"

# Get role_id
ROLE_ID=$(bao read -field=role_id auth/approle/role/$ROLE_NAME/role-id)
echo "   Role ID: $ROLE_ID"

# Generate secret_id
SECRET_ID=$(bao write -field=secret_id -f auth/approle/role/$ROLE_NAME/secret-id)
echo "   Secret ID: $SECRET_ID"

# Enable KV v2 secrets engine for apikeys
if ! bao secrets list 2>/dev/null | grep -q "^apikeys/$"; then
    bao secrets enable -path=apikeys kv-v2
    echo "✅ KV v2 secrets engine mounted at apikeys/"
else
    echo "✅ KV v2 secrets engine already mounted at apikeys/"
fi

# Write credentials to file
echo "💾 Writing credentials to $CREDENTIALS_FILE..."
cat > "$CREDENTIALS_FILE" << EOF
VAULT_ROLE_ID=$ROLE_ID
VAULT_SECRET_ID=$SECRET_ID
EOF

chmod 600 "$CREDENTIALS_FILE"
echo ""
echo "=========================================================="
echo "✅ OpenBao initialization complete!"
echo "📁 Credentials saved to: ./volumes/.vault-credentials"
echo "=========================================================="
echo ""

echo "🔄 OpenBao server is already running (PID: $SERVER_PID)"

wait $SERVER_PID
