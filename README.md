[![Modrinth](https://img.shields.io/badge/Modrinth-figura--unchained-%2300AF5C?style=flat-square&logo=modrinth&logoColor=white)](https://modrinth.com/mod/figura-unchained)

## This is the backend repository for Figura Unchained. 
**Looking for the addon?** Get the mod on [Modrinth](https://modrinth.com/mod/figura-unchained) or view the [Addon Source Code](https://github.com/bulbat0n/figura-unchained).

---

## 📖 About the Project

This is a custom backend for the Figura Unchained addon. It handles custom user authentication, avatar storage (NBT files), and WebSocket event broadcasting for players using offline-mode servers.

## 📂 Project Structure

* `server.py` — The main backend application.
* `admin.py` — CLI tool for secure server administration (broadcasts, toasts).
* `data/` — Directory created automatically to store the database, avatars and local session secrets.

## 🛠️ Setup & Installation

You can run this backend natively using a Python virtual environment or via Docker.

### Option A: Native (Python venv)
1. Clone the repository: `git clone https://github.com/bulbat0n/figura-unchained-backend.git`
2. Navigate to the directory: `cd figura-unchained-backend`
3. Create a virtual environment: `python3 -m venv venv`
4. Activate it: 
   * Linux/macOS: `source venv/bin/activate`
   * Windows: `venv\Scripts\activate`
5. Install dependencies: `pip install -r requirements.txt`

### Option B: Docker
If you prefer containerization, you can use the provided Docker setup.
1. Clone the repository and navigate to it.
2. Configure your environment variables (see Configuration below).
3. Build and run the container in the background using the command: `docker-compose up -d --build`

## ⚙️ Configuration (.env)

Create a `.env` file in the root directory (or copy `.env.example`). The backend requires the following variables to start:

* `PORT` — The port the backend will listen on.
* `DEBUG` — `true` or `false`. Enables detailed logging for HTTP requests and WebSocket events.
* `AVATAR_DIR` — Path to the directory where `.nbt` skins will be stored (e.g., `data/avatars`).
* `REQUIRE_AUTH` — `true` or `false`. If true, players must register and log in to upload avatars and broadcast pings.
* `MAX_PING_BPS` — Maximum bytes per second allowed for a single client's WebSocket ping data.
* `MAX_PING_SIZE` — Maximum size (in bytes) of a single WebSocket ping packet.
* `MAX_AVATAR_SIZE` — Maximum size (in bytes) allowed for an uploaded `.nbt` avatar file.
* `RATE_LIMIT_REQUESTS` — Number of HTTP requests allowed per IP address within the rate limit window.
* `RATE_LIMIT_WINDOW` — The time window (in seconds) for the HTTP rate limiter.
* `RATE_LIMIT_CLEANUP_INTERVAL` — Interval (in seconds) to periodically clean up expired rate limit data from memory.
* `WS_MAX_CONNECTIONS_PER_IP` — Maximum number of simultaneous WebSocket connections allowed from a single IP address.
* `WS_MAX_MESSAGES_PER_SEC` — Maximum number of WebSocket messages a client is allowed to send per second.
* `WS_MAX_SUBS_PER_CLIENT` — Maximum number of other players a single client can subscribe to for updates.
* `TRUSTED_PROXIES` — Comma-separated list of trusted proxy IPs or subnets (e.g., `127.0.0.1, ::1, 172.16.0.0/12`). Required to accurately read client IPs behind reverse proxies.
* `CUSTOM_REAL_IP_HEADER` — (Optional) A specific HTTP header to read the real client IP from if using a custom proxy setup (e.g., `CF-Connecting-IP`). Leave blank to use standard `X-Forwarded-For` logic.

## 🌐 Networking & Reverse Proxy

**Ports and Connections**
You **only** need to open backend's port on your firewall or router if you are connecting directly via LAN (or a virtual LAN). 

**Reverse Proxy (Nginx/Cloudflare)**
If you are hosting this publicly behind a reverse proxy (like Nginx), you must ensure the proxy passes the real client IP. If it doesn't, the backend rate-limiter will treat all players as a single IP and block the server.

Example for Nginx:
`proxy_set_header X-Forwarded-For $remote_addr;`

Make sure to add your proxy's internal IP to the `TRUSTED_PROXIES` variable in your `.env` file. *(Note: Admin commands are handled via local files, so the administration panel is inherently protected from network IP spoofing).*

## 🚀 Running the Server & Administration

**Start the server (Native):**
`python3 server.py`

**Administration (IPC CLI):**
The server uses a secure, file-based IPC queue for admin commands. You run these commands from the same machine or container where the server is hosted.

* Send a chat message to all connected players:
  `python3 admin.py chat "Hello everyone!"`
* Send a GUI toast notification:
  `python3 admin.py toast <type> "Title" "Description"`
  *(Types: 1 = Default, 2 = Warning, 3 = Error, 4 = Cheese)*

---

## ❗ Disclaimers & Legal

**This backend is NOT an official product of the Figura team and is NOT supported by them.** 
Figura Unchained is a third-party modification and backend implementation. Please do not bother the official Figura developers with issues, bugs, or questions related to this custom backend.

**Server Owner Responsibilities:**
By hosting this backend, you are solely responsible for the moderation and retention of data (including IP addresses and uploaded NBT files) on your server. The creator of this project assumes no liability for malicious, illegal, or NSFW content uploaded to third-party instances running this software.
