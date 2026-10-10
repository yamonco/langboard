#!/bin/bash

# Utility functions for docker scripts

# Function to validate PostgreSQL URL
validate_postgres_url() {
    local url="$1"
    local url_name="$2"

    if [ -n "$url" ]; then
        # Check if URL matches postgresql:// or postgres:// format
        if [[ ! "$url" =~ ^postgres(ql)?:// ]]; then
            echo "Error: $url_name must start with postgresql:// or postgres://"
            exit 1
        fi

        # Basic structure check: postgresql://user:pass@host:port/db
        if [[ ! "$url" =~ ^postgres(ql)?://[^:]+(:[^@]+)?@[^:]+:[0-9]+/.+$ ]]; then
            echo "Warning: $url_name may not be in correct format (postgresql://user:password@host:port/database)"
            read -p "Continue anyway? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi

        echo "✓ $url_name is valid"
    fi
}
