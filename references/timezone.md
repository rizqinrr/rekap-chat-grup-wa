# Timezone Notes

**Always verify first — do not assume.** Run `date '+%Y-%m-%d %H:%M:%S %Z %z'` and
`hermes config get timezone` on the actual host before writing any cron schedule.

## This container (verified 2026-10-27)

- Container clock: **UTC** (`offset +0000`), `/etc/timezone` empty, `HERMES_TIMEZONE` unset,
  `config timezone` empty.
- Earlier notes claiming Asia/Shanghai (UTC+8) were wrong — do not translate cron from them.
- WIB = UTC+7.

| WIB target | Cron (UTC) |
|---|---|
| 07:00 | `0 0 * * *` |
| 23:00 | `0 16 * * *` |

If `hermes config get timezone` returns a real zone (or `HERMES_TIMEZONE` is set), cron
expressions are interpreted in that zone instead — recompute the table from the value you read.

Always pass `schedule` on cron update; omitting it resets the schedule to `0 0 * * *`.
