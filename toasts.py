import json

TYPE_IDS = {"default": 0, "warning": 1, "error": 2}

OUTDATED_CLIENT_ERROR = "Please update Figura Unchained"

TOASTS = {
    "update": ("error", "Please update Figura Unchained", "Minimum version for your backend is {min_version}"),
    "rate": ("error", "Too many requests", "Try again later"),
    "auth_invalid": ("error", "Auth failed", "Invalid request"),
    "username": ("error", "Invalid username", "Use 3-16 characters: A-Z, 0-9, _"),
    "username_mismatch": ("error", "Invalid username", "Username does not match UUID"),
    "banned": ("error", "Account banned", ""),
    "registered": ("warning", "Malicious or NSFW content is prohibited", "Author IPs are logged by backend's owner"),
    "already_registered": ("error", "Already registered", "Use /figura-unchained login <password>"),
    "logged_in": ("default", "Logged in", ""),
    "not_registered": ("error", "Not registered", "Use /figura-unchained register <password>"),
    "wrong_password": ("error", "Wrong password", ""),
    "not_logged_in": ("error", "Not logged in", "Use /figura-unchained login <password>"),
    "auth_required_login": ("error", "Auth Required", "Type /figura-unchained login <password>"),
    "auth_required_register": ("error", "Auth Required", "Type /figura-unchained register <password>"),
    "authenticated": ("default", "Authenticated", "Connected successfully."),
    "report_invalid": ("error", "Report failed", "Invalid request"),
    "report_reason": ("error", "Report failed", "Reason must be 1-{reason_max} characters long"),
    "report_self": ("error", "Report failed", "You cannot report yourself"),
    "report_no_avatar": ("error", "Report failed", "This player has no avatar"),
    "report_limit": ("error", "Report failed", "Daily limit reached ({per_day} per day)"),
    "report_duplicate": ("error", "Report failed", "You already reported this player"),
    "report_sent": ("default", "Report sent", "Thank you, a moderator will review it"),
}


def fields(key, **values):
    kind, title, message = TOASTS[key]
    return {"title": title.format(**values), "message": message.format(**values), "type": kind}


def packet(key, **values):
    toast = fields(key, **values)
    return b'\x03' + bytes([TYPE_IDS[toast["type"]]]) + toast["title"].encode('utf-8') + b'\x00' + toast["message"].encode('utf-8')


def close_reason(key, **values):
    return json.dumps(fields(key, **values), separators=(',', ':')).encode('utf-8')
