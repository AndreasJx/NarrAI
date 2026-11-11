#!/bin/sh
set -eu

role="${SERVICE_ROLE:-service}"
path="${SERVICE_PATH:-}"
command="${START_COMMAND:-}"

if [ -n "$path" ] && [ -d "/workspace/$path" ]; then
  cd "/workspace/$path"
fi

if [ -n "$command" ]; then
  echo "Starting $role with configured command"
  exec sh -c "$command"
fi

if [ -f package.json ]; then
  if [ -f pnpm-lock.yaml ] && command -v corepack >/dev/null 2>&1; then
    corepack enable
    exec pnpm start
  fi
  exec npm start
fi

echo "No application command or manifest found for $role at ${path:-<unset>}." >&2
echo "Set ${role}_START_COMMAND in .env after implementing the service." >&2

if [ "$role" = "API" ] || [ "$role" = "WEB" ]; then
  export PLACEHOLDER_ROLE="$role"
  exec node -e '
    const http = require("http");
    const role = process.env.PLACEHOLDER_ROLE;
    const port = Number(process.env.PORT || 3000);
    http.createServer((req, res) => {
      const health = req.url === "/health";
      res.writeHead(health ? 200 : 503, {"content-type":"application/json"});
      res.end(JSON.stringify({
        status: health ? "placeholder" : "not_configured",
        service: role,
        message: "Configure START_COMMAND when application code is available"
      }));
    }).listen(port, "0.0.0.0");
  '
fi

exec node -e '
  console.error("Worker placeholder active; no jobs will be processed.");
  setInterval(() => {}, 2147483647);
'
