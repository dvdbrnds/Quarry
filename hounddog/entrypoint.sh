#!/bin/sh
# Runs as root at container start. Fixes DNS, then execs supervisord
# (also as root). Supervisord drops privileges per-process via user=appuser.

# Append public DNS resolvers as fallback for Docker's embedded DNS
if ! grep -q '8.8.8.8' /etc/resolv.conf 2>/dev/null; then
  printf '\nnameserver 8.8.8.8\nnameserver 1.1.1.1\nnameserver 8.8.4.4\n' >> /etc/resolv.conf
fi

exec "$@"
