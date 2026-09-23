#!/bin/sh
# Run inside the copied ALIVE NAS directory. Keeps existing private settings.
set -eu
cd "$(dirname "$0")"

if [ -e .env ]; then
  printf '%s\n' 'Existing .env kept unchanged.'
  exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
  printf '%s\n' 'OpenSSL is required to generate access tokens.' >&2
  exit 1
fi

umask 077
web_token=$(openssl rand -hex 32)
device_token=$(openssl rand -hex 32)
cat > .env <<EOF
# Private NAS settings. Never commit or share this file.
ALIVE_WEB_ORIGIN=https://jr-4b3.github.io
ALIVE_WEB_TOKEN=$web_token
ALIVE_DEVICE_TOKEN=$device_token
OPENAI_API_KEY=REPLACE_WITH_YOUR_OPENAI_API_KEY
EOF
chmod 600 .env
printf '%s\n' 'Created private .env with separate web and device tokens.'
printf '%s\n' 'Next: put your OpenAI API key into .env on the NAS before starting the container.'
