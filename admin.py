import sys
import json
import os
import re
import sqlite3
import time
import uuid

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
        return

    cmd_type = sys.argv[1].lower()

    if cmd_type == "reports":
        reports_command(sys.argv[2:])
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
            
    elif cmd_type == "online":
        data = {"type": "online"}

    else:
        print("Unknown command. Use 'chat', 'toast' or 'online'.")
        return

    token_file = "data/.admin_session"
    if not os.path.exists(token_file):
        print("Error: data/.admin_session not found. Is the server running?")
        return
        
    with open(token_file, "r") as f:
        data["token"] = f.read().strip()
        
    unique_id = uuid.uuid4().hex
    data["id"] = unique_id
    tmp_file = f"data/.admin_command_{unique_id}.tmp"
    final_file = f"data/.admin_command_{unique_id}.json"
        
    with open(tmp_file, "w") as f:
        json.dump(data, f)
        
    os.replace(tmp_file, final_file)

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
