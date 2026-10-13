#!/bin/sh
# Ensure reliable DNS resolvers are available at runtime.
# Docker overwrites /etc/resolv.conf at container start, so we can't
# set this at build time. We append public resolvers as fallbacks so
# external lookups (Okta, SMTP, Sentry, etc.) survive transient Docker
# DNS failures on Coolify/VPS hosts.
if ! grep -q '8.8.8.8' /etc/resolv.conf 2>/dev/null; then
  printf '\nnameserver 8.8.8.8\nnameserver 1.1.1.1\nnameserver 8.8.4.4\n' >> /etc/resolv.conf 2>/dev/null || true
fi

exec "$@"
