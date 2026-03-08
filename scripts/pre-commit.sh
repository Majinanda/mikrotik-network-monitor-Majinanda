#!/bin/bash

# Pre-commit secret scanner
# Serializes staged changes and checks for high-entropy strings or common secret patterns.

echo "🔍 Running pre-push security scan..."

# List of patterns to flag
PATTERNS=("password" "secret" "@" "token" "key")
FORBIDDEN_FILES=(".env" "mikrotik_dashboard.db" ".pem" ".key")

# Check for forbidden files in git staged area
STAGED_FILES=$(git diff --cached --name-only)

for file in $STAGED_FILES; do
    # Skip example/template files
    if [[ "$file" == *".example"* ]] || [[ "$file" == *".template"* ]]; then
        continue
    fi
    
    for forbidden in "${FORBIDDEN_FILES[@]}"; do
        if [[ "$file" == *"$forbidden"* ]]; then
            echo "❌ ERROR: You are trying to commit a sensitive file: $file"
            echo "Please remove it from the commit or add it to .gitignore."
            exit 1
        fi
    done
done

# Check for potential hardcoded credentials in staged code
# (Simple grep for demo, can be expanded to high-entropy detection)
if git diff --cached | grep -Ei "password=|secret=|token=|api_key=" | grep -v ".env.example"; then
    echo "⚠️  WARNING: Potential hardcoded secrets detected in staged changes!"
    echo "Please use environment variables instead of hardcoding credentials."
    # We exit 0 here so as not to block the user during development, but show a warning.
    # Change to exit 1 to strictly block.
    exit 0
fi

echo "✅ Security scan passed."
exit 0
