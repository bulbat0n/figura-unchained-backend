import hashlib
import uuid
import os
import re
import sys
import time
import secrets
import atexit
import sqlite3
import threading
import bcrypt
import jwt
import ipaddress
import asyncio
import logging
import json
import glob
import zlib
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
    "WS_MAX_MESSAGES_PER_SEC", "WS_MAX_SUBS_PER_CLIENT",
    "LOGIN_RATE_LIMIT_REQUESTS", "LOGIN_RATE_LIMIT_WINDOW",
    "MAX_AVATAR_UNPACKED_SIZE"
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
    LOGIN_RATE_LIMIT_REQUESTS = int(os.environ.get("LOGIN_RATE_LIMIT_REQUESTS"))
    LOGIN_RATE_LIMIT_WINDOW = int(os.environ.get("LOGIN_RATE_LIMIT_WINDOW"))
    MAX_AVATAR_UNPACKED_SIZE = int(os.environ.get("MAX_AVATAR_UNPACKED_SIZE"))
    if MAX_AVATAR_UNPACKED_SIZE < MAX_AVATAR_SIZE:
        config_errors.append("MAX_AVATAR_UNPACKED_SIZE must not be smaller than MAX_AVATAR_SIZE.")
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
log_formatter = logging.Formatter('[%(asctime)s] [%(levelname)-7s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

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
db_lock = threading.Lock()

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

def log_warn(msg):
    logging.warning(msg)

def log_error(msg, exc_info=False):
    logging.error(msg, exc_info=exc_info)

def log_debug(msg):
    if DEBUG:
        logging.debug(msg)

throttle_state = {}

def log_throttled(key, msg, interval=60):
    now = time.time()
    entry = throttle_state.get(key)
    if entry and now - entry[0] < interval:
        entry[1] += 1
        return
    suppressed = entry[1] if entry else 0
    throttle_state[key] = [now, 0]
    if suppressed:
        msg += f" (+{suppressed} similar suppressed)"
    logging.warning(msg)

def fmt_uuid(value):
    try:
        version = uuid.UUID(value).version
    except (ValueError, AttributeError, TypeError):
        return shown(value)
    return f"{value} (v{version if version else '?'})"

def shown(value, limit=40):
    text = str(value)
    return repr(text) if len(text) <= limit else f"<{len(text)} chars>"

def short_uuid(value):
    return str(value).split('-')[0]

def fmt_dur(seconds):
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"

def get_file_hash_sync(filepath):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def db_is_registered_sync(client_uuid):
    with db_lock:
        cursor = db_conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE uuid = ?", (client_uuid,))
        return cursor.fetchone() is not None

def db_register_sync(client_uuid, client_hash, real_ip):
    if db_is_registered_sync(client_uuid):
        return False
    hashed_pw = bcrypt.hashpw(client_hash.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    with db_lock:
        try:
            db_conn.execute("INSERT INTO users (uuid, password_hash, last_ip) VALUES (?, ?, ?)", (client_uuid, hashed_pw, real_ip))
            db_conn.commit()
        except sqlite3.IntegrityError:
            db_conn.rollback()
            return False
    return True

def db_login_sync(client_uuid, client_hash, real_ip):
    with db_lock:
        row = db_conn.execute("SELECT password_hash FROM users WHERE uuid = ?", (client_uuid,)).fetchone()
    if not row:
        return False
    if bcrypt.checkpw(client_hash.encode('utf-8'), row[0].encode('utf-8')):
        with db_lock:
            db_conn.execute("UPDATE users SET last_ip = ? WHERE uuid = ?", (real_ip, client_uuid))
            db_conn.commit()
        return True
    return False

def auth_status(request, client_uuid):
    if not REQUIRE_AUTH:
        return True, "auth-disabled"
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        raw_token = request.headers.get("token", "")
        if ":" in raw_token:
            token = raw_token.split(":", 1)[1]
    if not token:
        return False, "no-token"
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return False, "token-expired"
    except jwt.InvalidTokenError:
        return False, "token-invalid"
    if payload.get("uuid") != client_uuid:
        return False, "token-uuid-mismatch"
    return True, "ok"

def check_auth(request, client_uuid):
    return auth_status(request, client_uuid)[0]

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
auth_rate_limits = {}
AUTH_PATHS = ('/api/auth/register', '/api/auth/login')
WS_PATHS = ('/ws', '/api/ws', '/api//ws')

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
            log_throttled(f"rate:{real_ip}", f"[RATE] 429 ip={real_ip} exceeded {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW}s (last: {request.method} {request.path!r})")
            return web.json_response({"error": "Too Many Requests"}, status=429)

    if LOGIN_RATE_LIMIT_REQUESTS > 0 and request.method == "POST" and request.path in AUTH_PATHS:
        entry = auth_rate_limits.get(real_ip)
        if entry is None or current_time > entry["reset"]:
            entry = auth_rate_limits[real_ip] = {"count": 0, "reset": current_time + LOGIN_RATE_LIMIT_WINDOW}
        entry["count"] += 1
        if entry["count"] > LOGIN_RATE_LIMIT_REQUESTS:
            log_throttled(f"authrate:{real_ip}", f"[RATE] 429 ip={real_ip} exceeded {LOGIN_RATE_LIMIT_REQUESTS} auth attempts per {LOGIN_RATE_LIMIT_WINDOW}s ({request.path})")
            return web.json_response({"error": "Too Many Requests"}, status=429)

    ignore_logs = ['/api/version', '/api/limits', '/api/motd', '/api/', '/api', '/api/auth/register', '/api/auth/login']
    if request.path not in ignore_logs:
        log_debug(f"[HTTP] {request.method} {request.path!r} ip={real_ip}")

    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        logging.exception(f"[HTTP] Unhandled error in {request.method} {request.path!r} ip={real_ip}")
        if request.path in WS_PATHS:
            raise
        raise web.HTTPInternalServerError()

async def read_auth_body(request):
    try:
        body = await request.json()
    except Exception:
        return None, None, "body-is-not-json"
    if not isinstance(body, dict):
        return None, None, "body-is-not-an-object"
    client_uuid = body.get("uuid")
    client_hash = body.get("hash")
    if not isinstance(client_uuid, str) or not isinstance(client_hash, str):
        return None, None, "uuid-or-hash-missing"
    if not is_valid_uuid(client_uuid):
        return None, None, f"invalid-uuid-format {shown(client_uuid)}"
    if not client_hash:
        return None, None, "empty-hash"
    if len(client_hash.encode('utf-8')) > 72:
        return None, None, "hash-too-long"
    return client_uuid, client_hash, None

async def handle_api_check(request):
    return web.json_response({"status": "ok"})

async def handle_version(request):
    return web.json_response({"release": "0.1.5", "prerelease": "0.1.5", "unchained_api": 1})

async def handle_limits(request):
    return web.json_response({"rate": {"upload": MAX_PING_BPS, "download": MAX_PING_BPS}, "limits": {"maxAvatarSize": MAX_AVATAR_SIZE}})

async def handle_motd(request):
    return web.json_response({"text": "Figura Unchained Backend", "color": "gold"})

async def handle_register(request):
    ip = request['real_ip']
    client_uuid, client_hash, reason = await read_auth_body(request)
    if client_uuid is None:
        log_warn(f"[AUTH] register REJECT ip={ip} reason=bad-request: {reason}")
        return web.json_response({"error": "Invalid data format"}, status=400)
        
    success = await asyncio.to_thread(db_register_sync, client_uuid, client_hash, ip)
    if not success:
        log_info(f"[AUTH] register FAIL uuid={fmt_uuid(client_uuid)} ip={ip} reason=already-registered")
        return web.json_response({"error": "Already registered. Please login."}, status=409)
    
    token = jwt.encode({"uuid": client_uuid, "exp": datetime.now(timezone.utc) + timedelta(days=30)}, JWT_SECRET, algorithm="HS256")
    log_info(f"[AUTH] register OK uuid={fmt_uuid(client_uuid)} ip={ip}")
    return web.json_response({
        "status": "success", 
        "token": token, 
        "title": "Malicious or NSFW content is prohibited",
        "message": "Author IPs are logged by backend's owner"
    })

async def handle_login(request):
    ip = request['real_ip']
    client_uuid, client_hash, reason = await read_auth_body(request)
    if client_uuid is None:
        log_warn(f"[AUTH] login REJECT ip={ip} reason=bad-request: {reason}")
        return web.json_response({"error": "Invalid data format"}, status=400)
        
    success = await asyncio.to_thread(db_login_sync, client_uuid, client_hash, ip)
    if not success:
        registered = await asyncio.to_thread(db_is_registered_sync, client_uuid)
        why = "wrong-password" if registered else "uuid-not-registered"
        log_info(f"[AUTH] login FAIL uuid={fmt_uuid(client_uuid)} ip={ip} reason={why}")
        return web.json_response({"error": "Invalid password or UUID"}, status=401)
        
    token = jwt.encode({"uuid": client_uuid, "exp": datetime.now(timezone.utc) + timedelta(days=30)}, JWT_SECRET, algorithm="HS256")
    log_info(f"[AUTH] login OK uuid={fmt_uuid(client_uuid)} ip={ip}")
    return web.json_response({"status": "success", "token": token})

async def handle_user_profile(request):
    target_uuid = os.path.basename(request.match_info['uuid'])
    file_path = os.path.join(AVATAR_DIR, f"{target_uuid}.nbt")
    equipped = []
    
    if os.path.exists(file_path):
        if target_uuid not in hash_cache:
            hash_cache[target_uuid] = await asyncio.to_thread(get_file_hash_sync, file_path)
            
        equipped.append({"owner": target_uuid, "id": "avatar", "hash": hash_cache[target_uuid]})
        log_debug(f"[PROFILER] Serving profile {target_uuid}")
        
    return web.json_response({"equipped": equipped, "equippedBadges": {"pride": [], "special": []}}, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

async def download_avatar(request):
    target_uuid = os.path.basename(request.match_info['uuid'])
    file_path = os.path.join(AVATAR_DIR, f"{target_uuid}.nbt")
    if os.path.exists(file_path):
        log_debug(f"[DOWNLOAD] Serving file: {target_uuid}.nbt")
        return web.FileResponse(file_path, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})
    return web.json_response({"error": "Not found"}, status=404, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

class GzipValidator:
    def __init__(self, limit):
        self.limit = limit
        self.total = 0
        self.decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)
        self.members = 0

    def feed(self, data):
        buf = data
        while buf:
            if self.decomp.eof:
                self.decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)
            out = self.decomp.decompress(buf, 262144)
            self.total += len(out)
            if self.total > self.limit:
                return False
            if self.decomp.eof:
                self.members += 1
                buf = self.decomp.unused_data
            else:
                buf = self.decomp.unconsumed_tail
        return True

    def complete(self):
        return self.decomp.eof and self.members > 0 and self.total > 0

async def iter_upload_body(first_chunk, content):
    yield first_chunk
    async for chunk in content.iter_chunked(65536):
        yield chunk

def reject_upload(client_uuid, ip, status, reason, message):
    log_info(f"[UPLOAD] REJECT {status} uuid={fmt_uuid(client_uuid)} ip={ip} reason={reason}")
    return web.json_response({"error": message}, status=status)

async def upload_avatar(request):
    ip = request['real_ip']
    raw_token = request.headers.get('token', '')
    client_uuid = raw_token.split(':')[0] if ':' in raw_token else raw_token
    
    if not is_valid_uuid(client_uuid):
        log_warn(f"[UPLOAD] REJECT 400 ip={ip} reason=invalid-token-uuid value={shown(client_uuid)}")
        return web.json_response({"error": "Invalid token"}, status=400)
        
    authed, auth_reason = auth_status(request, client_uuid)
    if not authed:
        log_info(f"[UPLOAD] REJECT 401 uuid={fmt_uuid(client_uuid)} ip={ip} reason={auth_reason}")
        return web.json_response({"error": "Unauthorized. Please login."}, status=401)
        
    if request.content_length and request.content_length > MAX_AVATAR_SIZE:
        return reject_upload(client_uuid, ip, 413, f"too-large declared={request.content_length} limit={MAX_AVATAR_SIZE}", "File exceeds MAX_AVATAR_SIZE")

    file_path = os.path.join(AVATAR_DIR, f"{client_uuid}.nbt")
    loop = asyncio.get_running_loop()
    
    try:
        first_chunk_data = await request.content.read(65536)
    except Exception as e:
        return reject_upload(client_uuid, ip, 400, f"read-error {e!r}", "Read error")

    if not first_chunk_data:
        return reject_upload(client_uuid, ip, 400, "empty-body", "Empty file")

    if len(first_chunk_data) < 2 or first_chunk_data[:2] != b'\x1f\x8b':
        return reject_upload(client_uuid, ip, 400, "not-gzip", "Invalid format. Only compressed NBT allowed.")
    
    if len(first_chunk_data) > MAX_AVATAR_SIZE:
        return reject_upload(client_uuid, ip, 413, f"too-large size={len(first_chunk_data)} limit={MAX_AVATAR_SIZE}", "File exceeds MAX_AVATAR_SIZE")
    
    tmp_path = f"{file_path}.{secrets.token_hex(6)}.tmp"
    validator = GzipValidator(MAX_AVATAR_UNPACKED_SIZE)
    bytes_written = 0
    error = None

    try:
        with open(tmp_path, 'wb') as f:
            async for chunk in iter_upload_body(first_chunk_data, request.content):
                bytes_written += len(chunk)
                if bytes_written > MAX_AVATAR_SIZE:
                    error = reject_upload(client_uuid, ip, 413, f"too-large stream>{MAX_AVATAR_SIZE}", "File exceeds MAX_AVATAR_SIZE")
                    break
                try:
                    within_limit = await loop.run_in_executor(None, validator.feed, chunk)
                except zlib.error as e:
                    error = reject_upload(client_uuid, ip, 400, f"gzip-corrupt {e}", "Invalid format. Only compressed NBT allowed.")
                    break
                if not within_limit:
                    error = reject_upload(client_uuid, ip, 413, f"unpacked-too-large limit={MAX_AVATAR_UNPACKED_SIZE}", "File exceeds MAX_AVATAR_UNPACKED_SIZE")
                    break
                await loop.run_in_executor(None, f.write, chunk)

        if error is None and not validator.complete():
            error = reject_upload(client_uuid, ip, 400, "gzip-incomplete", "Invalid format. Only compressed NBT allowed.")

        if error is not None:
            return error

        os.replace(tmp_path, file_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    hash_cache[client_uuid] = await asyncio.to_thread(get_file_hash_sync, file_path)
    users_with_avatars.add(client_uuid)
    watchers = len(subscriptions.get(client_uuid, ()))
    log_info(f"[UPLOAD] OK uuid={fmt_uuid(client_uuid)} ip={ip} bytes={bytes_written} watchers={watchers}")

    if client_uuid in subscriptions:
        uuid_bytes = uuid.UUID(client_uuid).bytes
        event_packet = b'\x02' + uuid_bytes
        for sub_uuid in subscriptions[client_uuid]:
            if sub_uuid != client_uuid and sub_uuid in active_connections:
                await active_connections[sub_uuid].send_bytes(event_packet)
                log_debug(f"[EVENT-OUT] Skin update -> {sub_uuid}")

    return web.json_response({"status": "success"})

async def equip_avatar(request):
    return web.json_response({"status": "success"})

async def delete_avatar(request):
    ip = request['real_ip']
    raw_token = request.headers.get('token', '')
    client_uuid = raw_token.split(':')[0] if ':' in raw_token else raw_token
    
    if not is_valid_uuid(client_uuid):
        log_warn(f"[DELETE] REJECT 400 ip={ip} reason=invalid-token-uuid value={shown(client_uuid)}")
        return web.json_response({"error": "Invalid token"}, status=400)
        
    authed, auth_reason = auth_status(request, client_uuid)
    if not authed:
        log_info(f"[DELETE] REJECT 401 uuid={fmt_uuid(client_uuid)} ip={ip} reason={auth_reason}")
        return web.json_response({"error": "Unauthorized. Please login."}, status=401)

    file_path = os.path.join(AVATAR_DIR, f"{client_uuid}.nbt")
    if os.path.exists(file_path):
        await asyncio.to_thread(os.remove, file_path)
        users_with_avatars.discard(client_uuid)
        hash_cache.pop(client_uuid, None)
        log_info(f"[DELETE] OK uuid={fmt_uuid(client_uuid)} ip={ip}")
        
        if client_uuid in subscriptions:
            uuid_bytes = uuid.UUID(client_uuid).bytes
            event_packet = b'\x02' + uuid_bytes
            for sub_uuid in subscriptions[client_uuid]:
                if sub_uuid != client_uuid and sub_uuid in active_connections:
                    await active_connections[sub_uuid].send_bytes(event_packet)
                    log_debug(f"[EVENT-OUT] Skin deletion -> {sub_uuid}")
    else:
        log_info(f"[DELETE] uuid={fmt_uuid(client_uuid)} ip={ip} nothing to delete (no avatar stored)")
                        
    return web.json_response({"status": "deleted"})

async def websocket_handler(request):
    real_ip = request['real_ip']
    if ip_connections.get(real_ip, 0) >= WS_MAX_CONNECTIONS_PER_IP:
        log_throttled(f"wsip:{real_ip}", f"[WS] REJECT 429 ip={real_ip} reason=too-many-connections limit={WS_MAX_CONNECTIONS_PER_IP}")
        return web.Response(status=429)

    ip_connections[real_ip] = ip_connections.get(real_ip, 0) + 1
    
    try:
        ws = web.WebSocketResponse(heartbeat=25.0)
        await ws.prepare(request)
        
        raw_token = request.headers.get('token', '')
        client_uuid = raw_token.split(':')[0] if ':' in raw_token else raw_token
        
        if not is_valid_uuid(client_uuid):
            reason = "no-token-header" if not raw_token else "malformed-uuid"
            log_warn(f"[WS] REJECT ip={real_ip} reason={reason} value={shown(client_uuid)}")
            return ws
            
        is_authenticated, auth_reason = auth_status(request, client_uuid)

        file_path = os.path.join(AVATAR_DIR, f"{client_uuid}.nbt")
        has_avatar = os.path.exists(file_path)
        if has_avatar:
            users_with_avatars.add(client_uuid)
        else:
            users_with_avatars.discard(client_uuid)

        is_registered = None
        if REQUIRE_AUTH and not is_authenticated:
            is_registered = await asyncio.to_thread(db_is_registered_sync, client_uuid)

        previous = active_connections.get(client_uuid)
        if previous is not None and previous is not ws:
            log_warn(f"[WS] duplicate session uuid={fmt_uuid(client_uuid)} ip={real_ip}: an older connection with this UUID is still registered and is being replaced")

        active_connections[client_uuid] = ws
        connected_at = time.time()

        if not REQUIRE_AUTH:
            auth_text = "disabled"
        elif is_authenticated:
            auth_text = "yes"
        else:
            auth_text = f"NO reason={auth_reason} registered={'yes' if is_registered else 'no'}"
        log_info(f"[WS] + connect uuid={fmt_uuid(client_uuid)} ip={real_ip} auth={auth_text} avatar={'yes' if has_avatar else 'no'} online={len(active_connections)}")
        
        ping_bytes_sec = 0
        ping_reset_time = time.time()
        msg_count = 0
        msg_reset_time = time.time()
        client_subs = 0
        auth_msg = ""
        pings_in = 0
        pings_relayed = 0
        drops = {}

        def note_drop(kind, reason, detail=""):
            drops[reason] = drops.get(reason, 0) + 1
            if drops[reason] == 1:
                log_warn(f"[WS] dropped {kind} uuid={fmt_uuid(client_uuid)} ip={real_ip} reason={reason} {detail} (further drops this session are only counted)")
        
        try:
            await ws.send_bytes(b'\x00')
            
            if REQUIRE_AUTH:
                if not is_authenticated:
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
                    if not data:
                        continue
                    cmd = data[0]
                    
                    current_time = time.time()
                    if current_time - msg_reset_time > 1.0:
                        msg_count = 0
                        msg_reset_time = current_time
                    msg_count += 1
                    
                    if msg_count > WS_MAX_MESSAGES_PER_SEC:
                        note_drop("message", "message-rate-limit", f"limit={WS_MAX_MESSAGES_PER_SEC}/s")
                        await ws.send_bytes(b'\x05\x01')
                        continue
                    
                    if cmd == 0:
                        log_debug(f"[WS-TOKEN] Ignored token packet from {client_uuid}")
                        
                    elif cmd == 1:
                        pings_in += 1
                        if not is_authenticated:
                            note_drop("ping", "not-authenticated", "(player has to /figura-unchained login or register)")
                            toast_packet = b'\x03\x02' + "Auth Required".encode('utf-8') + b'\x00' + auth_msg.encode('utf-8')
                            await ws.send_bytes(toast_packet)
                            continue

                        if client_uuid not in users_with_avatars:
                            note_drop("ping", "no-avatar-uploaded", "(pings are relayed only for UUIDs that have an uploaded avatar)")
                            continue
                            
                        if len(data) > MAX_PING_SIZE:
                            note_drop("ping", "ping-too-large", f"size={len(data)} limit={MAX_PING_SIZE}")
                            await ws.send_bytes(b'\x05\x00') 
                            continue
                            
                        if current_time - ping_reset_time > 1.0:
                            ping_bytes_sec = 0
                            ping_reset_time = current_time
                            
                        ping_bytes_sec += len(data)
                        if ping_bytes_sec > MAX_PING_BPS:
                            note_drop("ping", "ping-rate-limit", f"limit={MAX_PING_BPS} B/s")
                            await ws.send_bytes(b'\x05\x01')
                            continue

                        uuid_bytes = uuid.UUID(client_uuid).bytes
                        s2c_packet = data[0:1] + uuid_bytes + data[1:]
                        
                        recipients = []
                        if client_uuid in subscriptions:
                            for sub_uuid in subscriptions[client_uuid]:
                                if sub_uuid != client_uuid and sub_uuid in active_connections:
                                    await active_connections[sub_uuid].send_bytes(s2c_packet)
                                    recipients.append(short_uuid(sub_uuid))
                        pings_relayed += 1
                        log_debug(f"[WS-PING] {short_uuid(client_uuid)} size={len(data)} -> {', '.join(recipients) if recipients else 'nobody'}")
                    
                    elif cmd == 2 and len(data) >= 17:
                        if client_subs >= WS_MAX_SUBS_PER_CLIENT:
                            note_drop("subscribe", "subscription-limit", f"limit={WS_MAX_SUBS_PER_CLIENT}")
                            continue
                        target_uuid = str(uuid.UUID(bytes=data[1:17]))
                        if target_uuid not in subscriptions:
                            subscriptions[target_uuid] = set()
                        if client_uuid not in subscriptions[target_uuid]:
                            subscriptions[target_uuid].add(client_uuid)
                            client_subs += 1
                        log_debug(f"[WS-SUB] {short_uuid(client_uuid)} -> {short_uuid(target_uuid)}")
                        
                        uuid_bytes = uuid.UUID(target_uuid).bytes
                        event_packet = b'\x02' + uuid_bytes
                        await ws.send_bytes(event_packet)
                    
                    elif cmd == 3 and len(data) >= 17:
                        target_uuid = str(uuid.UUID(bytes=data[1:17]))
                        if target_uuid in subscriptions and client_uuid in subscriptions[target_uuid]:
                            subscriptions[target_uuid].remove(client_uuid)
                            client_subs -= 1
                            log_debug(f"[WS-UNSUB] {short_uuid(client_uuid)} -/-> {short_uuid(target_uuid)}")
                    
                elif msg.type == WSMsgType.ERROR:
                    log_warn(f"[WS] error uuid={fmt_uuid(client_uuid)} ip={real_ip}: {ws.exception()!r}")
        except ConnectionError as e:
            log_info(f"[WS] connection lost uuid={fmt_uuid(client_uuid)} ip={real_ip}: {e!r}")
        except Exception:
            logging.exception(f"[WS] Unhandled error in session uuid={fmt_uuid(client_uuid)} ip={real_ip}")
        finally:
            current = active_connections.get(client_uuid)
            replaced = current is not None and current is not ws
            if current is ws:
                del active_connections[client_uuid]
            
            if not replaced:
                for target in list(subscriptions.keys()):
                    if client_uuid in subscriptions[target]:
                        subscriptions[target].remove(client_uuid)
                        if not subscriptions[target]:
                            del subscriptions[target]
                        
            drops_text = ", ".join(f"{k}={v}" for k, v in drops.items()) or "none"
            log_info(f"[WS] - disconnect uuid={fmt_uuid(client_uuid)} ip={real_ip} time={fmt_dur(time.time() - connected_at)} code={ws.close_code} pings={pings_in} relayed={pings_relayed} drops={drops_text} subs={client_subs} online={len(active_connections)}")
            if replaced:
                log_info(f"[WS] uuid={fmt_uuid(client_uuid)}: closed connection had already been replaced by a newer one; the newer session was left untouched")
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
        for ip in [ip for ip, d in auth_rate_limits.items() if now > d["reset"]]:
            del auth_rate_limits[ip]
        for key in [k for k, v in throttle_state.items() if now - v[0] > 600]:
            del throttle_state[key]

def process_admin_commands():
    commands = []
    for file_path in glob.glob("data/.admin_command_*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            commands.append(data)
        except Exception as e:
            logging.warning(f"[ADMIN] Unreadable command file {file_path}: {e!r}")
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
            
            if not packet:
                logging.warning(f"[ADMIN] Command {b_type!r} ignored (unknown type or empty content)")

            if packet:
                count = 0
                for ws in list(active_connections.values()):
                    try:
                        await ws.send_bytes(packet)
                        count += 1
                    except Exception as e:
                        logging.warning(f"[ADMIN] Failed to send to a client: {e!r}")
                logging.info(f"[ADMIN] Broadcasted {b_type} to {count} users.")

def log_task_exit(task):
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logging.error(f"[SYS] Background task {task.get_name()} crashed: {exc!r}", exc_info=exc)

async def start_background_tasks(app):
    app['cleanup_task'] = asyncio.create_task(cleanup_rate_limits(app), name="cleanup_rate_limits")
    app['admin_poller_task'] = asyncio.create_task(admin_command_poller(app), name="admin_command_poller")
    app['cleanup_task'].add_done_callback(log_task_exit)
    app['admin_poller_task'].add_done_callback(log_task_exit)

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

def log_startup_summary():
    with db_lock:
        users = db_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    avatars = len(glob.glob(os.path.join(AVATAR_DIR, "*.nbt")))
    log_info(f"[SYS] Starting on {HOST}:{PORT} | debug={DEBUG} require_auth={REQUIRE_AUTH} | registered_users={users} avatars={avatars}")
    log_info(f"[SYS] Limits: avatar={MAX_AVATAR_SIZE}B (unpacked {MAX_AVATAR_UNPACKED_SIZE}B), ping={MAX_PING_SIZE}B/{MAX_PING_BPS}Bps | http={RATE_LIMIT_REQUESTS}/{RATE_LIMIT_WINDOW}s, auth={LOGIN_RATE_LIMIT_REQUESTS}/{LOGIN_RATE_LIMIT_WINDOW}s | ws: {WS_MAX_CONNECTIONS_PER_IP} conn/ip, {WS_MAX_MESSAGES_PER_SEC} msg/s, {WS_MAX_SUBS_PER_CLIENT} subs | trusted_proxies={len(trusted_networks)}")

if __name__ == '__main__':
    try:
        log_startup_summary()
        web.run_app(app, host=HOST, port=PORT, access_log=None, print=None)
        log_info("[SYS] Server stopped")
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
