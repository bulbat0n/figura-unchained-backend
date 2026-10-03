import sys
import json
import os
import uuid

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 admin.py chat \"Your message here\"")
        print("  python3 admin.py toast <1/2/3/4> \"Title\" \"Description\"")
        print("    (1 = Default, 2 = Warning, 3 = Error, 4 = Cheese)")
        return

    cmd_type = sys.argv[1].lower()
    
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
            
    else:
        print("Unknown command. Use 'chat' or 'toast'.")
        return

    token_file = "data/.admin_session"
    if not os.path.exists(token_file):
        print("Error: data/.admin_session not found. Is the server running?")
        return
        
    with open(token_file, "r") as f:
        data["token"] = f.read().strip()
        
    unique_id = uuid.uuid4().hex
    tmp_file = f"data/.admin_command_{unique_id}.tmp"
    final_file = f"data/.admin_command_{unique_id}.json"
        
    with open(tmp_file, "w") as f:
        json.dump(data, f)
        
    os.replace(tmp_file, final_file)
    print(f"Command '{cmd_type}' sent to the server queue!")

if __name__ == "__main__":
    main()
