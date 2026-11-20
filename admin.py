import sys
import json
import os
import re
import sqlite3
import time
import uuid
import hashlib
import toastfit

def clean(value):
    return "".join(c if c.isprintable() else "?" for c in str(value))

def print_online(result):
    players = result.get("players", [])
    print(f"Online: {result.get('online', len(players))}")
    for p in players:
        print()
        print(f"{clean(p.get('username'))}  {clean(p.get('duration'))}  (since {clean(p.get('connected_at'))})  ip:  {clean(p.get('ip'))}")
        uuids = [f"canonical={clean(p.get('canonical_uuid'))}"] + [re.sub(r"^\((session|world)_uuid=", r"(\1=", clean(a)) for a in re.findall(r"\([^()]*\)", str(p.get("aliases") or ""))]
        print(f"  {'uuids':<9}{'  '.join(uuids)}")
        print(f"  {'version':<9}{clean(p.get('version'))}")
        info = [f"auth={clean(p.get('auth'))}"]
        if p.get("reason"):
            info.append(f"reason={clean(p.get('reason'))}")
        if p.get("registered"):
            info.append(f"registered={clean(p.get('registered'))}")
        info.append(f"avatar={clean(p.get('avatar'))}")
        print(f"  {'info':<9}{'  '.join(info)}")

UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

def resolve_target(value):
    if UUID_RE.match(value):
        return value.lower()
    digest = hashlib.md5(f"OfflinePlayer:{value}".encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest, version=3))

def open_db():
    if not os.path.exists("data/users.db"):
        print("Error: data/users.db not found.")
        return None
    db = sqlite3.connect("data/users.db", timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS bans (uuid TEXT PRIMARY KEY, username TEXT, reason TEXT, created_at INTEGER NOT NULL)")
    return db

def erase_account(db, target_uuid):
    row = db.execute("SELECT username FROM users WHERE uuid = ?", (target_uuid,)).fetchone()
    removed = db.execute("DELETE FROM users WHERE uuid = ?", (target_uuid,)).rowcount
    if db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_badges'").fetchone():
        db.execute("DELETE FROM user_badges WHERE uuid = ?", (target_uuid,))
    path = os.path.join(os.environ.get("AVATAR_DIR") or "data/avatars", f"{target_uuid}.nbt")
    avatar = os.path.exists(path)
    if avatar:
        os.remove(path)
    return (row[0] if row else None), bool(removed), avatar

def queue_command(data):
    token_file = "data/.admin_session"
    if not os.path.exists(token_file):
        return None
    with open(token_file, "r") as f:
        data["token"] = f.read().strip()
    unique_id = uuid.uuid4().hex
    data["id"] = unique_id
    tmp_file = f"data/.admin_command_{unique_id}.tmp"
    with open(tmp_file, "w") as f:
        json.dump(data, f)
    os.replace(tmp_file, f"data/.admin_command_{unique_id}.json")
    return unique_id

def accounts_command(cmd, args):
    if cmd in ("delete", "ban", "unban") and not args:
        print(f"Usage: python3 admin.py {cmd} <nickname|uuid>" + (" [reason]" if cmd == "ban" else ""))
        return
    db = open_db()
    if db is None:
        return
    try:
        if cmd == "bans":
            rows = db.execute("SELECT uuid, username, reason, created_at FROM bans ORDER BY created_at").fetchall()
            if not rows:
                print("No bans.")
            for buuid, bname, breason, created in rows:
                print(f"{buuid}  {clean(bname or '?')}  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created))}  {clean(breason or '')}")
            return
        target_uuid = resolve_target(args[0])
        if cmd == "unban":
            removed = db.execute("DELETE FROM bans WHERE uuid = ?", (target_uuid,)).rowcount
            db.commit()
            print(f"{target_uuid} unbanned." if removed else f"{target_uuid} was not banned.")
            return
        name, removed, avatar = erase_account(db, target_uuid)
        if cmd == "ban":
            label = name if name is not None else (None if UUID_RE.match(args[0]) else args[0])
            reason = " ".join(args[1:]).strip() or None
            db.execute("INSERT OR REPLACE INTO bans (uuid, username, reason, created_at) VALUES (?, ?, ?, ?)", (target_uuid, label, reason, int(time.time())))
        db.commit()
    finally:
        db.close()
    print(f"{target_uuid} ({clean(name or '?')}): account {'deleted' if removed else 'not found'}, avatar {'deleted' if avatar else 'not found'}" + (", banned." if cmd == "ban" else "."))
    if queue_command({"type": "ban_account" if cmd == "ban" else "delete_account", "uuid": target_uuid}):
        print("Server notified: watchers refresh the avatar" + (", the player is disconnected." if cmd == "ban" else "."))
    else:
        print("Server is not running: nothing to notify.")

def reports_command(args):
    if not os.path.exists("data/users.db"):
        print("Error: data/users.db not found.")
        return
    db = sqlite3.connect("data/users.db", timeout=10)
    try:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'reports'").fetchone() is None:
            print("No reports yet.")
            return
        if args and args[0] == "close":
            if len(args) < 2 or not args[1].isdigit():
                print("Usage: python3 admin.py reports close <id>")
                return
            cursor = db.execute("UPDATE reports SET status = 'closed' WHERE id = ?", (int(args[1]),))
            db.commit()
            print(f"Report #{args[1]} closed." if cursor.rowcount else f"Report #{args[1]} not found.")
            return
        show_all = bool(args) and args[0] == "all"
        query = "SELECT id, created_at, reporter_name, reporter_uuid, target_name, target_uuid, avatar_hash, reason, status FROM reports"
        if not show_all:
            query += " WHERE status = 'open'"
        rows = db.execute(query + " ORDER BY id").fetchall()
    finally:
        db.close()
    if not rows:
        print("No reports." if show_all else "No open reports.")
        return
    for rid, created, rname, ruuid, tname, tuuid, ahash, reason, status in rows:
        print(f"#{rid} [{status}] {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created))}")
        print(f"  target    {clean(tname)} ({tuuid})")
        print(f"  reporter  {clean(rname or '?')} ({ruuid})")
        print(f"  avatar    {clean(ahash or '?')}")
        print(f"  reason    {clean(reason)}")

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 admin.py chat \"Your message here\"")
        print("  python3 admin.py toast <1/2/3/4> \"Title\" \"Description\"")
        print("    (1 = Default, 2 = Warning, 3 = Error, 4 = Cheese)")
        print("  python3 admin.py online")
        print("  python3 admin.py reports [all]")
        print("  python3 admin.py reports close <id>")
        print("  python3 admin.py delete <nickname|uuid>")
        print("  python3 admin.py ban <nickname|uuid> [reason]")
        print("  python3 admin.py unban <nickname|uuid>")
        print("  python3 admin.py bans")
        return

    cmd_type = sys.argv[1].lower()

    if cmd_type == "reports":
        reports_command(sys.argv[2:])
        return

    if cmd_type in ("delete", "ban", "unban", "bans"):
        accounts_command(cmd_type, sys.argv[2:])
        return
    
    if cmd_type == "chat":
        if len(sys.argv) < 3:
            print("Usage: python3 admin.py chat \"Your message here\"")
            return
            
        msg = sys.argv[2]
        if not msg.strip():
            print("Error: Message cannot be empty.")
            return
            
        data = {"type": "chat", "message": msg}
        
    elif cmd_type == "toast":
        if len(sys.argv) < 4:
            print("Usage: python3 admin.py toast <1/2/3/4> \"Title\" \"Description\"")
            print("  (1 = Default, 2 = Warning, 3 = Error, 4 = Cheese)")
            return
            
        try:
            t_input = int(sys.argv[2])
        except ValueError:
            print("Usage: python3 admin.py toast <1/2/3/4> \"Title\" \"Description\"")
            print("  (1 = Default, 2 = Warning, 3 = Error, 4 = Cheese)")
            return
            
        mapping = {1: 0, 2: 1, 3: 2, 4: 3}
        data = {
            "type": "toast",
            "toast_type": mapping.get(t_input, 0),
            "title": sys.argv[3],
            "desc": sys.argv[4] if len(sys.argv) > 4 else ""
        }
        
        if not data["title"].strip() and not data["desc"].strip():
            print("Error: Both title and description cannot be empty.")
            return

        too_long = [(name, len(lines)) for name, lines in (("title", toastfit.split_lines(data["title"])), ("text", toastfit.split_lines(data["desc"]))) if len(lines) > toastfit.MAX_LINES]
        if too_long:
            names = " and the ".join(name for name, _ in too_long)
            sizes = ", ".join(f"{name}: {count} lines" for name, count in too_long)
            print(f"The {names} of this toast {'do' if len(too_long) > 1 else 'does'} not fit into the frame ({sizes}, max {toastfit.MAX_LINES}).")
            try:
                answer = input("Send the toast anyway? y/n: ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                print("Toast not sent.")
                return
            
    elif cmd_type == "online":
        data = {"type": "online"}

    else:
        print("Unknown command. Use 'chat', 'toast' or 'online'.")
        return

    unique_id = queue_command(data)
    if unique_id is None:
        print("Error: data/.admin_session not found. Is the server running?")
        return

    if cmd_type == "online":
        result_name = f".admin_result_{unique_id}.json"
        result_file = f"data/{result_name}"
        for _ in range(100):
            if result_name in os.listdir("data"):
                with open(result_file, "r", encoding="utf-8") as f:
                    result = json.load(f)
                os.remove(result_file)
                print_online(result)
                return
            time.sleep(0.1)
        print("Error: no answer from the server. Is it running?")
        return

    print(f"Command '{cmd_type}' sent to the server queue!")

if __name__ == "__main__":
    main()
