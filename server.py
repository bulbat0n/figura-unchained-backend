import hashlib
import uuid
import os
import re
import sys
import time
import secrets
import atexit
import sqlite3
import bcrypt
import jwt
import ipaddress
import asyncio
import logging
import json
import glob
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta, timezone
from aiohttp import web, WSMsgType
from dotenv import load_dotenv

load_dotenv()

REQUIRED_VARS = [
    "PORT", "DEBUG", "AVATAR_DIR", "MAX_PING_BPS", 
    "MAX_PING_SIZE", "MAX_AVATAR_SIZE", "REQUIRE_AUTH",
    "RATE_LIMIT_REQUESTS", "RATE_LIMIT_WINDOW", "TRUSTED_PROXIES",
    "RATE_LIMIT_CLEANUP_INTERVAL", "WS_MAX_CONNECTIONS_PER_IP",
    "WS_MAX_MESSAGES_PER_SEC", "WS_MAX_SUBS_PER_CLIENT"
]

missing_vars = [var for var in REQUIRED_VARS if not os.environ.get(var)]

if missing_vars:
    print(f"[FATAL ERROR] Missing required variables in .env: {', '.join(missing_vars)}")
    sys.exit(1)

config_errors = []

try:
    PORT = int(os.environ.get("PORT"))
except ValueError:
    config_errors.append("PORT must be an integer.")

HOST = os.environ.get("IP", "0.0.0.0")
DEBUG_env = os.environ.get("DEBUG").lower()
if DEBUG_env not in ["true", "false"]:
    config_errors.append(f"DEBUG must be 'true' or 'false', got '{DEBUG_env}'")
else:
    DEBUG = DEBUG_env == "true"
    
REQUIRE_AUTH_env = os.environ.get("REQUIRE_AUTH").lower()
if REQUIRE_AUTH_env not in ["true", "false"]:
    config_errors.append(f"REQUIRE_AUTH must be 'true' or 'false', got '{REQUIRE_AUTH_env}'")
else:
    REQUIRE_AUTH = REQUIRE_AUTH_env == "true"

try:
    MAX_PING_BPS = int(os.environ.get("MAX_PING_BPS"))
    MAX_PING_SIZE = int(os.environ.get("MAX_PING_SIZE"))
    MAX_AVATAR_SIZE = int(os.environ.get("MAX_AVATAR_SIZE"))
    RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS"))
    RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW"))
    RATE_LIMIT_CLEANUP_INTERVAL = int(os.environ.get("RATE_LIMIT_CLEANUP_INTERVAL"))
    WS_MAX_CONNECTIONS_PER_IP = int(os.environ.get("WS_MAX_CONNECTIONS_PER_IP"))
    WS_MAX_MESSAGES_PER_SEC = int(os.environ.get("WS_MAX_MESSAGES_PER_SEC"))
    WS_MAX_SUBS_PER_CLIENT = int(os.environ.get("WS_MAX_SUBS_PER_CLIENT"))
except ValueError:
    config_errors.append("Limits and intervals must be integers.")

AVATAR_DIR = os.environ.get("AVATAR_DIR")

CUSTOM_REAL_IP_HEADER = os.environ.get("CUSTOM_REAL_IP_HEADER")
if CUSTOM_REAL_IP_HEADER:
    CUSTOM_REAL_IP_HEADER = CUSTOM_REAL_IP_HEADER.strip()

trusted_networks = []
for net in os.environ.get("TRUSTED_PROXIES").split(","):
    net = net.strip()
    if not net:
        continue
    try:
        trusted_networks.append(ipaddress.ip_network(net))
    except ValueError:
        config_errors.append(f"Invalid TRUSTED_PROXIES format: {net}")

if config_errors:
    print("[FATAL ERROR] .env syntax/value errors found:")
    for err in config_errors:
        print(f"  - {err}")
    sys.exit(1)

os.makedirs("data", exist_ok=True)
os.makedirs(AVATAR_DIR, exist_ok=True)

log_level = logging.DEBUG if DEBUG else logging.INFO
log_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(log_formatter)

file_handler = RotatingFileHandler('data/server.log', maxBytes=5*1024*1024, backupCount=3)
file_handler.setFormatter(log_formatter)

logging.basicConfig(level=log_level, handlers=[stdout_handler, file_handler])

def save_secure_file(path, content):
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    mode = 0o600
    with open(os.open(path, flags, mode), "w") as f:
        f.write(content)

db_conn = sqlite3.connect('data/users.db', check_same_thread=False)
db_conn.execute('CREATE TABLE IF NOT EXISTS users (uuid TEXT PRIMARY KEY, password_hash TEXT, last_ip TEXT)')
db_conn.commit()

ADMIN_SESSION_TOKEN = secrets.token_hex(32)
save_secure_file("data/.admin_session", ADMIN_SESSION_TOKEN)

JWT_SECRET_FILE = "data/.jwt_secret"
if not os.path.exists(JWT_SECRET_FILE):
    JWT_SECRET = secrets.token_hex(64)
    save_secure_file(JWT_SECRET_FILE, JWT_SECRET)
else:
    with open(JWT_SECRET_FILE, "r") as f:
        JWT_SECRET = f.read().strip()

def cleanup_admin_session():
    if os.path.exists("data/.admin_session"):
        os.remove("data/.admin_session")

atexit.register(cleanup_admin_session)

UUID_REGEX = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

def is_valid_uuid(val):
    return bool(val and UUID_REGEX.match(val))

def log_info(msg):
    logging.info(msg)

def log_debug(msg):
    if DEBUG:
        logging.debug(msg)

def hex_dump(data):
    return data.hex().upper()

def get_file_hash_sync(filepath):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def db_is_registered_sync(client_uuid):
    cursor = db_conn.cursor()
    cursor.execute("SELECT 1 FROM users WHERE uuid = ?", (client_uuid,))
    return cursor.fetchone() is not None

def db_register_sync(client_uuid, client_hash, real_ip):
    cursor = db_conn.cursor()
    cursor.execute("SELECT uuid FROM users WHERE uuid = ?", (client_uuid,))
    if cursor.fetchone():
        return False
    hashed_pw = bcrypt.hashpw(client_hash.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    cursor.execute("INSERT INTO users (uuid, password_hash, last_ip) VALUES (?, ?, ?)", (client_uuid, hashed_pw, real_ip))
    db_conn.commit()
    return True

def db_login_sync(client_uuid, client_hash, real_ip):
    cursor = db_conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE uuid = ?", (client_uuid,))
    row = cursor.fetchone()
    if not row:
        return False
    if bcrypt.checkpw(client_hash.encode('utf-8'), row[0].encode('utf-8')):
        cursor.execute("UPDATE users SET last_ip = ? WHERE uuid = ?", (real_ip, client_uuid))
        db_conn.commit()
        return True
    return False

def check_auth(request, client_uuid):
    if not REQUIRE_AUTH:
        return True
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        raw_token = request.headers.get("token", "")
        if ":" in raw_token:
            token = raw_token.split(":", 1)[1]
    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            return payload.get("uuid") == client_uuid
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return False
    return False

def get_real_ip(request):
    try:
        client_ip = ipaddress.ip_address(request.remote)
    except ValueError:
        return request.remote

    is_trusted = any(client_ip in net for net in trusted_networks)
    
    if is_trusted:
        if CUSTOM_REAL_IP_HEADER:
            custom_ip = request.headers.get(CUSTOM_REAL_IP_HEADER)
            if custom_ip:
                return custom_ip.split(',')[0].strip()
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(',')[0].strip()
        xreal = request.headers.get("X-Real-IP")
        if xreal:
            return xreal.strip()
            
    return request.remote

active_connections = {}
subscriptions = {}
users_with_avatars = set()
rate_limits = {}
hash_cache = {}
ip_connections = {}

@web.middleware
async def security_middleware(request, handler):
    real_ip = get_real_ip(request)
    request['real_ip'] = real_ip
    
    current_time = time.time()
    if real_ip not in rate_limits:
        rate_limits[real_ip] = {"count": 0, "reset": current_time + RATE_LIMIT_WINDOW}
        
    if current_time > rate_limits[real_ip]["reset"]:
        rate_limits[real_ip] = {"count": 1, "reset": current_time + RATE_LIMIT_WINDOW}
    else:
        rate_limits[real_ip]["count"] += 1
        if rate_limits[real_ip]["count"] > RATE_LIMIT_REQUESTS:
            log_debug(f"[HTTP] Rate limit exceeded for {real_ip}")
            return web.json_response({"error": "Too Many Requests"}, status=429)

    ignore_logs = ['/api/version', '/api/limits', '/api/motd', '/api/', '/api', '/api/auth/register', '/api/auth/login']
    if request.path not in ignore_logs:
        log_debug(f"[HTTP] {request.method} {request.path} | IP: {real_ip}")
        
    return await handler(request)

async def handle_api_check(request):
    return web.json_response({"status": "ok"})

async def handle_version(request):
    return web.json_response({"release": "0.1.5", "prerelease": "0.1.5", "unchained_api": 1})

async def handle_limits(request):
    return web.json_response({"rate": {"upload": MAX_PING_BPS, "download": MAX_PING_BPS}, "limits": {"maxAvatarSize": MAX_AVATAR_SIZE}})

async def handle_motd(request):
    return web.json_response({"text": "Figura Unchained Backend", "color": "gold"})

async def handle_register(request):
    body = await request.json()
    client_uuid = body.get("uuid")
    client_hash = body.get("hash")
    
    if not is_valid_uuid(client_uuid) or not client_hash:
        return web.json_response({"error": "Invalid data format"}, status=400)
        
    success = await asyncio.to_thread(db_register_sync, client_uuid, client_hash, request['real_ip'])
    if not success:
        return web.json_response({"error": "Already registered. Please login."}, status=409)
    
    token = jwt.encode({"uuid": client_uuid, "exp": datetime.now(timezone.utc) + timedelta(days=30)}, JWT_SECRET, algorithm="HS256")
    log_info(f"[AUTH] Registered UUID {client_uuid[:8]} from IP {request['real_ip']}")
    return web.json_response({
        "status": "success", 
        "token": token, 
        "title": "Malicious or NSFW content is prohibited",
        "message": "Author IPs are logged by backend's owner"
    })

async def handle_login(request):
    body = await request.json()
    client_uuid = body.get("uuid")
    client_hash = body.get("hash")
    
    if not is_valid_uuid(client_uuid) or not client_hash:
        return web.json_response({"error": "Invalid data format"}, status=400)
        
    success = await asyncio.to_thread(db_login_sync, client_uuid, client_hash, request['real_ip'])
    if not success:
        return web.json_response({"error": "Invalid password or UUID"}, status=401)
        
    token = jwt.encode({"uuid": client_uuid, "exp": datetime.now(timezone.utc) + timedelta(days=30)}, JWT_SECRET, algorithm="HS256")
    log_info(f"[AUTH] Logged in UUID {client_uuid[:8]} from IP {request['real_ip']}")
    return web.json_response({"status": "success", "token": token})

async def handle_user_profile(request):
    target_uuid = os.path.basename(request.match_info['uuid'])
    file_path = os.path.join(AVATAR_DIR, f"{target_uuid}.nbt")
    equipped = []
    
    if os.path.exists(file_path):
        if target_uuid not in hash_cache:
            hash_cache[target_uuid] = await asyncio.to_thread(get_file_hash_sync, file_path)
            
        equipped.append({"owner": target_uuid, "id": "avatar", "hash": hash_cache[target_uuid]})
        log_debug(f"[PROFILER] Serving profile {target_uuid[:8]}")
        
    return web.json_response({"equipped": equipped, "equippedBadges": {"pride": [], "special": []}}, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

async def download_avatar(request):
    target_uuid = os.path.basename(request.match_info['uuid'])
    file_path = os.path.join(AVATAR_DIR, f"{target_uuid}.nbt")
    if os.path.exists(file_path):
        log_debug(f"[DOWNLOAD] Serving file: {target_uuid}.nbt")
        return web.FileResponse(file_path, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})
    return web.json_response({"error": "Not found"}, status=404, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

async def upload_avatar(request):
    raw_token = request.headers.get('token', '')
    client_uuid = raw_token.split(':')[0] if ':' in raw_token else raw_token
    
    if not is_valid_uuid(client_uuid):
        return web.json_response({"error": "Invalid token"}, status=400)
        
    if not check_auth(request, client_uuid):
        return web.json_response({"error": "Unauthorized. Please login."}, status=401)
        
    if request.content_length and request.content_length > MAX_AVATAR_SIZE:
        return web.json_response({"error": "File exceeds MAX_AVATAR_SIZE"}, status=413)

    file_path = os.path.join(AVATAR_DIR, f"{client_uuid}.nbt")
    loop = asyncio.get_running_loop()
    
    try:
        first_chunk_data = await request.content.read(65536)
    except Exception:
        return web.json_response({"error": "Read error"}, status=400)

    if not first_chunk_data:
        return web.json_response({"error": "Empty file"}, status=400)

    if len(first_chunk_data) < 2 or first_chunk_data[:2] != b'\x1f\x8b':
        return web.json_response({"error": "Invalid format. Only compressed NBT allowed."}, status=400)
    
    if len(first_chunk_data) > MAX_AVATAR_SIZE:
        return web.json_response({"error": "File exceeds MAX_AVATAR_SIZE"}, status=413)
    
    bytes_written = len(first_chunk_data)
    with open(file_path, 'wb') as f:
        await loop.run_in_executor(None, f.write, first_chunk_data)
        
        async for chunk in request.content.iter_chunked(65536):
            bytes_written += len(chunk)
            if bytes_written > MAX_AVATAR_SIZE:
                os.remove(file_path)
                return web.json_response({"error": "File exceeds MAX_AVATAR_SIZE"}, status=413)
            await loop.run_in_executor(None, f.write, chunk)
            
    hash_cache[client_uuid] = await asyncio.to_thread(get_file_hash_sync, file_path)
    users_with_avatars.add(client_uuid)
    log_info(f"[UPLOAD] UUID {client_uuid[:8]} saved skin ({bytes_written} bytes).")

    if client_uuid in subscriptions:
        uuid_bytes = uuid.UUID(client_uuid).bytes
        event_packet = b'\x02' + uuid_bytes
        for sub_uuid in subscriptions[client_uuid]:
            if sub_uuid != client_uuid and sub_uuid in active_connections:
                await active_connections[sub_uuid].send_bytes(event_packet)
                log_debug(f"[EVENT-OUT] Skin update -> {sub_uuid[:8]}")

    return web.json_response({"status": "success"})

async def equip_avatar(request):
    return web.json_response({"status": "success"})

async def delete_avatar(request):
    raw_token = request.headers.get('token', '')
    client_uuid = raw_token.split(':')[0] if ':' in raw_token else raw_token
    
    if not is_valid_uuid(client_uuid):
        return web.json_response({"error": "Invalid token"}, status=400)
        
    if not check_auth(request, client_uuid):
        return web.json_response({"error": "Unauthorized. Please login."}, status=401)

    file_path = os.path.join(AVATAR_DIR, f"{client_uuid}.nbt")
    if os.path.exists(file_path):
        await asyncio.to_thread(os.remove, file_path)
        users_with_avatars.discard(client_uuid)
        hash_cache.pop(client_uuid, None)
        log_info(f"[DELETE] Deleted skin for: {client_uuid[:8]}")
        
        if client_uuid in subscriptions:
            uuid_bytes = uuid.UUID(client_uuid).bytes
            event_packet = b'\x02' + uuid_bytes
            for sub_uuid in subscriptions[client_uuid]:
                if sub_uuid != client_uuid and sub_uuid in active_connections:
                    await active_connections[sub_uuid].send_bytes(event_packet)
                    log_debug(f"[EVENT-OUT] Skin deletion -> {sub_uuid[:8]}")
                        
    return web.json_response({"status": "deleted"})

async def websocket_handler(request):
    real_ip = request['real_ip']
    if ip_connections.get(real_ip, 0) >= WS_MAX_CONNECTIONS_PER_IP:
        return web.Response(status=429)

    ip_connections[real_ip] = ip_connections.get(real_ip, 0) + 1
    
    try:
        ws = web.WebSocketResponse(heartbeat=25.0)
        await ws.prepare(request)
        
        raw_token = request.headers.get('token', '')
        client_uuid = raw_token.split(':')[0] if ':' in raw_token else raw_token
        
        if not is_valid_uuid(client_uuid):
            log_info(f"[WS] Connection rejected (invalid token) from IP: {real_ip}")
            return ws
            
        is_authenticated = check_auth(request, client_uuid)

        file_path = os.path.join(AVATAR_DIR, f"{client_uuid}.nbt")
        if os.path.exists(file_path):
            users_with_avatars.add(client_uuid)
        else:
            users_with_avatars.discard(client_uuid)

        active_connections[client_uuid] = ws
        log_info(f"[WS] + Connected {client_uuid[:8]} (Auth: {is_authenticated}). Online: {len(active_connections)}")
        
        ping_bytes_sec = 0
        ping_reset_time = time.time()
        msg_count = 0
        msg_reset_time = time.time()
        client_subs = 0
        auth_msg = ""
        
        try:
            await ws.send_bytes(b'\x00')
            
            if REQUIRE_AUTH:
                if not is_authenticated:
                    is_registered = await asyncio.to_thread(db_is_registered_sync, client_uuid)
                    if is_registered:
                        auth_msg = "Type /figura-unchained login <password>"
                    else:
                        auth_msg = "Type /figura-unchained register <password>"
                    toast_packet = b'\x03\x02' + "Auth Required".encode('utf-8') + b'\x00' + auth_msg.encode('utf-8')
                    await ws.send_bytes(toast_packet)
                else:
                    toast_packet = b'\x03\x00' + "Authenticated".encode('utf-8') + b'\x00' + "Connected successfully.".encode('utf-8')
                    await ws.send_bytes(toast_packet)
            
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    data = msg.data
                    cmd = data[0]
                    
                    current_time = time.time()
                    if current_time - msg_reset_time > 1.0:
                        msg_count = 0
                        msg_reset_time = current_time
                    msg_count += 1
                    
                    if msg_count > WS_MAX_MESSAGES_PER_SEC:
                        await ws.send_bytes(b'\x05\x01')
                        continue
                    
                    if cmd == 0:
                        log_debug(f"[WS-TOKEN] Ignored token packet from {client_uuid[:8]}")
                        
                    elif cmd == 1:
                        if not is_authenticated:
                            toast_packet = b'\x03\x02' + "Auth Required".encode('utf-8') + b'\x00' + auth_msg.encode('utf-8')
                            await ws.send_bytes(toast_packet)
                            continue

                        if client_uuid not in users_with_avatars:
                            continue
                            
                        if len(data) > MAX_PING_SIZE:
                            log_debug(f"[WS-PING-LIMIT] {client_uuid[:8]} exceeded size ({len(data)} bytes)")
                            await ws.send_bytes(b'\x05\x00') 
                            continue
                            
                        if current_time - ping_reset_time > 1.0:
                            ping_bytes_sec = 0
                            ping_reset_time = current_time
                            
                        ping_bytes_sec += len(data)
                        if ping_bytes_sec > MAX_PING_BPS:
                            log_debug(f"[WS-PING-LIMIT] {client_uuid[:8]} exceeded rate limit")
                            await ws.send_bytes(b'\x05\x01')
                            continue

                        log_debug(f"[WS-PING-IN] From {client_uuid[:8]} | RAW: {hex_dump(data)}")
                        uuid_bytes = uuid.UUID(client_uuid).bytes
                        s2c_packet = data[0:1] + uuid_bytes + data[1:]
                        
                        if client_uuid in subscriptions:
                            for sub_uuid in subscriptions[client_uuid]:
                                if sub_uuid != client_uuid and sub_uuid in active_connections:
                                    await active_connections[sub_uuid].send_bytes(s2c_packet)
                                    log_debug(f"[WS-PING-OUT] To {sub_uuid[:8]} | RAW: {hex_dump(s2c_packet)}")
                    
                    elif cmd == 2 and len(data) >= 17:
                        if client_subs >= WS_MAX_SUBS_PER_CLIENT:
                            continue
                        target_uuid = str(uuid.UUID(bytes=data[1:17]))
                        if target_uuid not in subscriptions:
                            subscriptions[target_uuid] = set()
                        if client_uuid not in subscriptions[target_uuid]:
                            subscriptions[target_uuid].add(client_uuid)
                            client_subs += 1
                        log_debug(f"[WS-SUB] {client_uuid[:8]} -> {target_uuid[:8]}")
                        
                        uuid_bytes = uuid.UUID(target_uuid).bytes
                        event_packet = b'\x02' + uuid_bytes
                        await ws.send_bytes(event_packet)
                    
                    elif cmd == 3 and len(data) >= 17:
                        target_uuid = str(uuid.UUID(bytes=data[1:17]))
                        if target_uuid in subscriptions and client_uuid in subscriptions[target_uuid]:
                            subscriptions[target_uuid].remove(client_uuid)
                            client_subs -= 1
                            log_debug(f"[WS-UNSUB] {client_uuid[:8]} -/-> {target_uuid[:8]}")
                    
                elif msg.type == WSMsgType.ERROR:
                    log_info(f"[WS] Error in {client_uuid[:8]}: {ws.exception()}")
        finally:
            if client_uuid in active_connections:
                del active_connections[client_uuid]
            
            for target in list(subscriptions.keys()):
                if client_uuid in subscriptions[target]:
                    subscriptions[target].remove(client_uuid)
                    if not subscriptions[target]:
                        del subscriptions[target]
                        
            log_info(f"[WS] - Disconnected {client_uuid[:8]}. Online: {len(active_connections)}")
    finally:
        ip_connections[real_ip] -= 1
        if ip_connections[real_ip] <= 0:
            del ip_connections[real_ip]

    return ws

async def cleanup_rate_limits(app):
    while True:
        await asyncio.sleep(RATE_LIMIT_CLEANUP_INTERVAL)
        now = time.time()
        expired = [ip for ip, data in rate_limits.items() if now > data["reset"]]
        for ip in expired:
            del rate_limits[ip]

def process_admin_commands():
    commands = []
    for file_path in glob.glob("data/.admin_command_*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            commands.append(data)
        except Exception:
            pass
        finally:
            try:
                os.remove(file_path)
            except OSError:
                pass
    return commands

async def admin_command_poller(app):
    while True:
        await asyncio.sleep(1)
        commands = await asyncio.to_thread(process_admin_commands)
        
        for data in commands:
            if data.get("token") != ADMIN_SESSION_TOKEN:
                logging.warning("[ADMIN] Invalid session token in command file.")
                continue
                
            b_type = data.get("type")
            packet = None
            
            if b_type == "chat":
                msg = data.get("message", "")
                if msg:
                    packet = b'\x04' + msg.encode('utf-8')
                    
            elif b_type == "toast":
                t_type = int(data.get("toast_type", 0))
                title = data.get("title", "")
                desc = data.get("desc", "")
                if title or desc:
                    packet = b'\x03' + bytes([t_type]) + title.encode('utf-8') + b'\0' + desc.encode('utf-8')
            
            if packet:
                count = 0
                for ws in list(active_connections.values()):
                    try:
                        await ws.send_bytes(packet)
                        count += 1
                    except Exception as e:
                        logging.debug(f"[ADMIN] Failed to send to a client: {e}")
                logging.info(f"[ADMIN] Broadcasted {b_type} to {count} users.")

async def start_background_tasks(app):
    app['cleanup_task'] = asyncio.create_task(cleanup_rate_limits(app))
    app['admin_poller_task'] = asyncio.create_task(admin_command_poller(app))

async def cleanup_background_tasks(app):
    app['cleanup_task'].cancel()
    app['admin_poller_task'].cancel()
    try:
        await app['cleanup_task']
    except asyncio.CancelledError:
        pass
    try:
        await app['admin_poller_task']
    except asyncio.CancelledError:
        pass

app = web.Application(middlewares=[security_middleware], client_max_size=MAX_AVATAR_SIZE)

app.on_startup.append(start_background_tasks)
app.on_cleanup.append(cleanup_background_tasks)

app.router.add_get('/api/', handle_api_check)
app.router.add_get('/api', handle_api_check)
app.router.add_get('/api/version', handle_version)
app.router.add_get('/api/limits', handle_limits)
app.router.add_get('/api/motd', handle_motd)
app.router.add_post('/api/auth/register', handle_register)
app.router.add_post('/api/auth/login', handle_login)
app.router.add_get(r'/api/{uuid:[0-9a-fA-F\-]{36}}', handle_user_profile)
app.router.add_get(r'/api/avatar/{uuid:[0-9a-fA-F\-]{36}}', download_avatar)
app.router.add_get(r'/assets/v2/{uuid:[0-9a-fA-F\-]{36}}', download_avatar)
app.router.add_get(r'/api/{uuid:[0-9a-fA-F\-]{36}}/avatar', download_avatar)
app.router.add_put('/api/avatar', upload_avatar)
app.router.add_post('/api/equip', equip_avatar)
app.router.add_delete('/api/avatar', delete_avatar)
app.router.add_get('/ws', websocket_handler)
app.router.add_get('/api/ws', websocket_handler)
app.router.add_get('/api//ws', websocket_handler)

if __name__ == '__main__':
    try:
        log_info(f"Starting Server on host {HOST} port {PORT}...")
        web.run_app(app, host=HOST, port=PORT, access_log=None, print=None)
    except OSError as e:
        if e.errno in (98, 10048):
            print(f"\n[FATAL ERROR] Port {PORT} is already in use!")
            print("HOW TO FIX THIS:")
            print(f"1. Close the program holding port {PORT}")
            print("2. OR open .env, change PORT to a different number")
            print("   and update the 'Server IP' in Figura mod settings to localhost:new_port")
            print("\nExiting...")
            sys.exit(1)
        else:
            raise
