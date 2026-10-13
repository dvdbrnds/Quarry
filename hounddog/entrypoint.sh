#!/bin/sh
# Runs as root at container start. Fixes DNS, then drops to appuser.
#
# Docker overwrites /etc/resolv.conf at container start with its own
# embedded DNS (127.0.0.11). On some Coolify/VPS hosts this resolver
# intermittently fails, causing ConnectError on Okta/SMTP/Sentry calls.
# We append public resolvers as fallback.

if ! grep -q '8.8.8.8' /etc/resolv.conf 2>/dev/null; then
  printf '\nnameserver 8.8.8.8\nnameserver 1.1.1.1\nnameserver 8.8.4.4\n' >> /etc/resolv.conf
fi

exec gosu appuser "$@"
