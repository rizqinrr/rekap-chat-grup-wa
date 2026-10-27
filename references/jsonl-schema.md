# JSONL Log Schema

```json
{"ts": 1783736100, "sender": "Nama Kamu", "body": "test"}
```

- `ts`: UNIX epoch seconds from `msg.key.timestamp`, fallback `Date.now()`
- `sender`: display name from `event.senderName`, fallback to sender ID
- `body`: trimmed message text

One JSON object per line. File path: `~/.hermes/platforms/whatsapp/group_logs/<chat_id>@g.us.jsonl`.
