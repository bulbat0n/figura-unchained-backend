# Figura Unchained

An open-source synchronization backend and companion Fabric addon for self-hosted Figura deployments.

The project is designed for self-hosted environments and does not rely on external paid services or subscriptions.🫣️

The project provides an alternative infrastructure for avatar synchronization in private communities, LAN networks, development environments, and experimental server setups.

---

## ✨ Features

* Real-time avatar synchronization using WebSockets
* Self-hosted backend deployment
* Asynchronous architecture built for multiple concurrent clients
* Support for custom avatar storage and distribution
* Lightweight Fabric addon integration

---

## 🏗️ Architecture

The project consists of two components:

### Addon (`/addon`)

A Fabric mod responsible for client-side integration and communication with the backend service.

### Backend (`/backend`)

A Python-based server using `aiohttp` for avatar distribution, synchronization, and WebSocket communication.

---

## 📦 Dependencies

This project requires the official Figura mod to function.

You can download the required version here:

- Official repository: https://github.com/FiguraMC/Figura/tree/1.21.10

---

## 🚀 Installation

### Client Setup

1. Install the required version of Figura.
2. Download the latest release of Figura Unchained.
3. Place the addon `.jar` file into your `mods` directory.
4. Connect to your backend server in mod settings(BACKEND_IP:PORT)

### Backend Setup

#### Clone the repository

```bash
git clone https://github.com/bulbat0n/figura-unchained.git
cd figura-unchained/backend
```

#### Create a virtual environment

```bash
python3 -m venv venv
```

#### Activate the environment

**Linux / macOS**

```bash
source venv/bin/activate
```

**Windows**

```powershell
venv\Scripts\activate
```

#### Install dependencies

```bash
pip install -r requirements.txt
```

#### Create and configure .env

```bash
cp .env.example .env
```

```env
PORT=YOUR_PORT(required)
DEBUG=true/false(false by default)
AVATAR_DIR=your_avatar_dir(avatars by default)
```

#### Start the server

```bash
python3 server.py
```

---

## 🤝 Contributing

Contributions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Commit your changes.
4. Open a pull request.

---

## ⚠️ Known Issues

The following issues are currently known and will be addressed in future updates:

- No verification system

---

## ⚠️ Disclaimer

This project is an independent open-source development effort.

It is not affiliated with, endorsed by, or associated with the Figura project or its contributors.

Users are responsible for complying with all applicable licenses, terms of service, and local regulations when using this software.

