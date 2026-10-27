# Group intake: who gets through, and why a group goes silent

## The gate

Every inbound group message is filtered in the bridge **before** it reaches the model, in
`scripts/whatsapp-bridge/allowlist.js` → `matchesInboundWhatsAppGroup()`:

| `WHATSAPP_GROUP_POLICY` | Groups that pass |
|---|---|
| `open` | every group |
| `allowlist` | only the group JIDs listed in `WHATSAPP_GROUP_ALLOWED_USERS` |
| `disabled`, `pairing` | none |

- An **empty** `WHATSAPP_GROUP_ALLOWED_USERS` admits **no** group (secure default); the entry
  `*` admits **every** group.
- The gate runs before mention filtering, so a rejected group never reaches mention detection
  and tagging changes nothing. The rejection is not silent to the operator: the bridge logs it
  with the chat id (see below).
- Sender allowlisting is a **DM** concern. In groups the policy gates the group only, so with a
  wide-open group policy any member who mentions the bot reaches it; `WHATSAPP_REQUIRE_MENTION`
  still decides when it answers.

## Opening every group without opening every DM

`WHATSAPP_GROUP_POLICY=open` does not boot on its own — the gateway logs
`Refusing to start: whatsapp has dm_policy/group_policy set to 'open' but neither
GATEWAY_ALLOW_ALL_USERS nor WHATSAPP_ALLOW_ALL_USERS is enabled` — and those allow-all flags
open DMs to everyone, which defeats a strict DM allowlist.

To admit every group while the DM allowlist stays intact, keep the policy and widen only the
group list:

```
WHATSAPP_GROUP_POLICY=allowlist
WHATSAPP_GROUP_ALLOWED_USERS=*
```

A new group then works immediately — no per-group edit, no restart. Side effect: the silent
recorder writes JSONL for every group the account sits in, so cron summaries must stay scoped
per group ID.

## Config is read at gateway start, not per message

The Python adapter injects the bridge's env (`WHATSAPP_GROUP_POLICY`,
`WHATSAPP_GROUP_ALLOWED_USERS`, `WHATSAPP_REQUIRE_MENTION`, mention patterns, …) when it spawns
the Node bridge, and the WhatsApp plugin has no config watcher. Editing `.env` therefore does
nothing until the gateway restarts — and the restart must come from an external terminal, never
from inside an agent session.

## Prove which policy is actually live

`.env` shows what you *intend*; the running bridge holds what it was **started** with. Read the
live process's environment rather than trusting the file:

```
tr '\0' '\n' < /proc/<bridge_pid>/environ | grep '^WHATSAPP_'
```

Take the pid from the process list (`… bridge.js --port <n> --session <dir>`). Two more cross-checks
belong in the same pass: `/health` `scriptHash` against the copy on disk says whether the running
bridge is the patched one, and the gateway's own pid environment says which values the parent
would inject on the next respawn. Any difference means the change is pending a restart, not applied.

## Learning a group's ID without being admitted yet

Every rejected message is appended to the bridge log **with its chat id**, so a single message
in a new group is enough:

```
{"event":"ignored","reason":"group_policy_rejected","chatId":"<group>@g.us","senderAltId":"<phone>@s.whatsapp.net"}
```

Read the log, take `chatId`, add it to `WHATSAPP_GROUP_ALLOWED_USERS` (or switch to `*`), restart.
`allowlist_mismatch` is the DM-side counterpart and carries the sender JID instead. Asking the
bot "what is this group's id?" only works in a group the policy already admits.

## Symptom → cause

| Symptom | Cause |
|---|---|
| Bot answers in one group, silent in another | the silent group is not admitted by the policy |
| Goes quiet right after a `.env` edit | change is inert until the gateway restarts |
| Gateway will not start after a policy change | `open` set without an `*_ALLOW_ALL_USERS` flag |
| `failed to decrypt message` / `No session found to decrypt message` | session-dir ownership or permissions, not policy — the message arrived but could not be decrypted |
| Outbound works, inbound never reaches the gateway | stale/failed bridge process (check `ps` and `/health`) |
