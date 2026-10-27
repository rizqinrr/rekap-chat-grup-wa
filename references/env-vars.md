# Env Var Reference

| Variable | Values | Purpose |
|----------|--------|---------|
| WHATSAPP_ENABLED | true/false | Enable WhatsApp platform |
| WHATSAPP_MODE | bot / self-chat | Bot uses dedicated number; self-chat shares user number |
| WHATSAPP_DM_POLICY | open / allowlist / pairing / disabled | DM intake policy |
| WHATSAPP_GROUP_POLICY | open / allowlist / pairing / disabled | Group intake policy |
| WHATSAPP_ALLOWED_USERS | CSV phone numbers without +, or with `@s.whatsapp.net` suffix | DM allowlist |
| WHATSAPP_GROUP_ALLOWED_USERS | CSV group IDs | Group allowlist |
| WHATSAPP_REQUIRE_MENTION | true/false | Require @mention for group responses |
| cron.wrap_response | true/false | Strip cron delivery headers/footers |

Set via `hermes config set KEY VALUE` when the key lives in `config.yaml`; WhatsApp bridge vars (`WHATSAPP_*`) are read from `.env` and must be set there directly. On Docker installs, the active `.env` is at `$HERMES_HOME/.env` (e.g. `$HERMES_HOME/.env`).
