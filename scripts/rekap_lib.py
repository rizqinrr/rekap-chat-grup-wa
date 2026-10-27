"""Pembuat digest obrolan grup WhatsApp + arsip link + pemangkasan (no-LLM).

Kebijakan retensi (ditetapkan Kiki, 27 Okt 2026):
  - LINK disimpan PERMANEN di group_logs/links/<chat_id>.jsonl (dedupe per URL).
  - Chat biasa dipangkas setelah CHAT_RETENTION_DAYS hari.
  - Sesi grup di state.db dipangkas setelah idle CHAT_RETENTION_DAYS hari.
  - Ekstraksi link HARUS jalan sebelum pemangkasan apa pun.
  - Pemangkasan menempel di job rekap yang sudah ada (07:00 WIB), bukan job baru.
  - Semua pemangkasan murni script (0 token LLM) dan WAJIB senyap: stdout script
    ini disuntikkan ke prompt agen, jadi jangan pernah print apa pun di sini.

Sumber data: <LOG_DIR>/<chat_id>.jsonl
Tiap baris: {"ts": <epoch detik>, "sender": "...", "body": "..."}
"""

import json
import os
import re
import sqlite3
import subprocess
import datetime
import urllib.request

HERMES_HOME = os.environ.get("HERMES_HOME") or "$HERMES_HOME"
LOG_DIR = os.environ.get("GROUP_LOG_DIR") or os.path.join(
    HERMES_HOME, "platforms", "whatsapp", "group_logs"
)
LINKS_DIR = os.path.join(LOG_DIR, "links")
BRIDGE_URL = os.environ.get("WHATSAPP_BRIDGE_URL") or "http://localhost:3000"
HERMES_CLI = os.environ.get("HERMES_CLI") or "/opt/hermes/bin/hermes"
STATE_DB = os.path.join(HERMES_HOME, "state.db")

WINDOW_HOURS = 24         # jendela data untuk rekap harian
# 0 = matikan pemangkasan (tombol darurat untuk Kiki)
CHAT_RETENTION_DAYS = int(os.environ.get("CHAT_RETENTION_DAYS", "3"))
MIN_MESSAGES = 5          # di bawah ini dianggap grup sepi -> NO_ACTIVITY
MAX_MESSAGES = 120        # batas baris per grup untuk digest
MAX_CHARS = 3500          # batas panjang digest per grup
MIN_WORDS = 3             # buang pesan sepele dari digest
MAX_CONTEXT = 160         # panjang cuplikan pesan di arsip link
SESSION_PRUNE_STAMP = ".last_session_prune"   # penanda harian prune state.db
CLI_TIMEOUT = 60          # detik, batas waktu per perintah hapus sesi

URL_RE = re.compile(r"https?://[^\s<>\"')]+")


def log_path(chat_id):
    return os.path.join(LOG_DIR, chat_id + ".jsonl")


def links_path(chat_id):
    return os.path.join(LINKS_DIR, chat_id + ".jsonl")


def group_name(chat_id):
    """Nama grup dari bridge lokal (gratis, tidak pakai token)."""
    try:
        with urllib.request.urlopen(f"{BRIDGE_URL}/chat/{chat_id}", timeout=5) as resp:
            return json.load(resp).get("name") or chat_id
    except Exception:
        return chat_id


def load_rows(chat_id, hours=WINDOW_HOURS):
    """Ambil (ts, sender, body) dalam jendela waktu.

    TANPA filter jumlah kata, supaya pesan yang isinya cuma link tetap terbaca
    oleh arsip. Filter kata dilakukan terpisah di build_digest().
    """
    path = log_path(chat_id)
    if not os.path.exists(path):
        return []
    cutoff = datetime.datetime.now(datetime.timezone.utc).timestamp() - hours * 3600
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            ts = entry.get("ts") or 0
            if ts < cutoff:
                continue
            rows.append(
                (ts, entry.get("sender") or "?", (entry.get("body") or "").strip())
            )
    return rows


def archive_links(chat_id, rows):
    """Simpan link baru ke arsip permanen. Return jumlah link baru."""
    path = links_path(chat_id)
    existing = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    existing.add(json.loads(line)["url"])
                except Exception:
                    continue

    fresh = []
    for ts, sender, body in rows:
        for url in URL_RE.findall(body):
            url = url.rstrip(".,;:!?)]}\"'")
            if url in existing:
                continue
            existing.add(url)
            fresh.append(
                {
                    "ts": ts,
                    "sender": sender,
                    "url": url,
                    "context": body[:MAX_CONTEXT],
                }
            )

    if fresh:
        os.makedirs(LINKS_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for entry in fresh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(fresh)


def build_digest(chat_id, hours=WINDOW_HOURS):
    """Teks digest untuk prompt cron, atau None kalau grup sepi/tidak ada data."""
    rows = load_rows(chat_id, hours)
    if not rows:
        return None

    # 1) Arsipkan link LEBIH DULU — sebelum apa pun dipangkas.
    archive_links(chat_id, rows)

    # 2) Sisanya untuk digest: buang pesan terlalu pendek.
    rows = [r for r in rows if len(r[2].split()) >= MIN_WORDS]
    if len(rows) < MIN_MESSAGES:
        return None

    rows = rows[-MAX_MESSAGES:]
    counts = {}
    for _, sender, _ in rows:
        counts[sender] = counts.get(sender, 0) + 1
    top = ", ".join(
        f"{name} ({n} pesan)"
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1])[:5]
    )

    out = [
        f"GRUP: {group_name(chat_id)}",
        f"chat_id: {chat_id}",
        f"jumlah pesan ({hours} jam terakhir): {len(rows)}",
        f"pengirim teratas: {top}",
        "--- isi obrolan (urut waktu, UTC) ---",
    ]
    for ts, sender, body in rows:
        stamp = datetime.datetime.fromtimestamp(
            ts, datetime.timezone.utc
        ).strftime("%d/%m %H:%M")
        out.append(f"[{stamp}] {sender}: {body}")

    text = "\n".join(out)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[...dipotong karena kepanjangan...]"
    return text


def prune_chat(chat_id, days=None):
    """Buang baris chat yang lebih tua dari `days` hari. Return jumlah dibuang.

    Dipanggil main() SETELAH build_digest(): digest dibangun lebih dulu (dan link
    sudah terarsip), baru chat lama dibuang. Ditulis lewat temp-file + os.replace
    supaya file tidak pernah setengah jadi.

    Catatan: bridge menambah baris per pesan lewat appendFileSync (buka-tutup),
    jadi menukar file aman. Sisa jendela sangat kecil: pesan yang masuk di antara
    pembacaan dan os.replace bisa hilang — karena itu pemangkasan hanya membuang
    data yang jauh lebih tua dari jendela rekap.
    """
    days = CHAT_RETENTION_DAYS if days is None else days
    if days <= 0:
        return 0

    path = log_path(chat_id)
    if not os.path.exists(path):
        return 0

    cutoff = datetime.datetime.now(datetime.timezone.utc).timestamp() - days * 86400
    kept, dropped = [], 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            raw = line.strip()
            if not raw:
                continue
            try:
                ts = json.loads(raw).get("ts") or 0
            except Exception:
                kept.append(raw)
                continue
            if ts < cutoff:
                dropped += 1
            else:
                kept.append(raw)

    if not dropped:
        return 0

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for raw in kept:
            fh.write(raw + "\n")
    os.replace(tmp, path)
    return dropped


def session_prune_candidates(days=None, db_path=None):
    """ID sesi grup yang idle lebih dari `days` hari.

    PENTING: last_activity_at dan started_at di state.db adalah EPOCH DETIK
    (float), bukan string tanggal — perbandingan string akan salah dan bisa
    menyeret semua sesi. Selalu bandingkan sebagai angka.
    """
    days = CHAT_RETENTION_DAYS if days is None else days
    db = db_path or STATE_DB
    if not os.path.exists(db):
        return []

    cutoff = datetime.datetime.now(datetime.timezone.utc).timestamp() - days * 86400
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = con.execute(
            """select id from sessions
               where chat_id like '%@g.us'
                 and coalesce(last_activity_at, started_at) < ?""",
            (cutoff,),
        )
        return [row[0] for row in cur.fetchall()]
    finally:
        con.close()


def prune_state_db(days=None, dry_run=False, db_path=None, cli=None):
    """Hapus sesi grup lama di state.db. Sekali per hari. Return daftar ID terhapus.

    Sengaja SENYAP (tidak print) dan tidak pernah melempar error: pemangkasan
    gagal tidak boleh merusak job rekap.
    """
    days = CHAT_RETENTION_DAYS if days is None else days
    if days <= 0:
        return []

    stamp = os.path.join(HERMES_HOME, "state", SESSION_PRUNE_STAMP)
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    if not dry_run:
        try:
            if os.path.exists(stamp):
                with open(stamp, encoding="utf-8") as fh:
                    if fh.read().strip() == today:
                        return []      # sudah dipangkas hari ini
        except Exception:
            pass

    candidates = session_prune_candidates(days, db_path)
    if dry_run:
        return candidates

    cli = cli or HERMES_CLI
    removed = []
    for session_id in candidates:
        try:
            result = subprocess.run(
                [cli, "sessions", "delete", session_id, "--yes"],
                capture_output=True,
                text=True,
                timeout=CLI_TIMEOUT,
            )
            if result.returncode == 0:
                removed.append(session_id)
        except Exception:
            continue

    try:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write(today)
    except Exception:
        pass
    return removed


def main(chat_id):
    """Entry point pembungkus per grup: digest dulu, pemangkasan kemudian."""
    digest = build_digest(chat_id)

    # Pemangkasan (murni script, 0 token) menempel di job yang sama.
    try:
        prune_chat(chat_id)
    except Exception:
        pass
    try:
        prune_state_db()
    except Exception:
        pass

    print(digest if digest else "NO_ACTIVITY")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("NO_ACTIVITY")
    else:
        main(sys.argv[1])
