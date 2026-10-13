#!/bin/sh
# Runs as root at container start. Fixes DNS, fixes fd permissions,
# then drops to appuser via gosu.

# 1. Append public DNS resolvers as fallback for Docker's embedded DNS
if ! grep -q '8.8.8.8' /etc/resolv.conf 2>/dev/null; then
  printf '\nnameserver 8.8.8.8\nnameserver 1.1.1.1\nnameserver 8.8.4.4\n' >> /etc/resolv.conf
fi

# 2. Make stdout/stderr writable by appuser — gosu changes uid but
#    /dev/stdout and /dev/stderr are owned by root, so supervisord
#    (which logs to /dev/stdout) gets PermissionError without this.
chmod 777 /dev/stdout /dev/stderr 2>/dev/null || true

exec gosu appuser "$@"
