# ###########################################################################
# ###########################################################################
# ####                                                                   ####
# ####   LEGACY-1.9.5   LEGACY-1.9.5   LEGACY-1.9.5   LEGACY-1.9.5       ####
# ####                                                                   ####
# ####   Compatibility for Figura Unchained 1.9.5 and older.             ####
# ####                                                                   ####
# ####   Old addons ignore "title" / "message" / "type" and show         ####
# ####   "<their own title> / <HTTP code>: <error>". Every response      ####
# ####   they can display therefore gets a short "error" that still      ####
# ####   fits into the toast.                                            ####
# ####                                                                   ####
# ####   DELETE ALL OF IT WHEN MIN_ADDON_VERSION >= 1.9.6:               ####
# ####     grep -rn "LEGACY-1.9.5" .                                     ####
# ####   and remove every line it finds, then delete this file.          ####
# ####   The server warns on startup once this file is dead code.        ####
# ####                                                                   ####
# ###########################################################################
# ###########################################################################

OBSOLETE_FROM = (1, 9, 6)

ERRORS = {
    "rate": "Too Many Requests",
    "auth_invalid": "Invalid data format",
    "username": "Invalid username",
    "username_mismatch": "Username does not match UUID",
    "banned": "Account banned",
    "already_registered": "Already registered",
    "not_registered": "Not registered",
    "wrong_password": "Wrong password",
    "not_logged_in": "Not logged in",
    "report_invalid": "Invalid report",
    "report_reason": "Reason must be 1-{reason_max} characters long",
    "report_self": "You cannot report yourself",
    "report_no_avatar": "This player has no avatar",
    "report_limit": "Daily limit reached ({per_day} per day)",
    "report_duplicate": "You already reported this player",
}


def add_error(body, key, **values):
    text = ERRORS.get(key)
    if text is not None and "error" not in body:
        body["error"] = text.format(**values)


def warn_if_obsolete(min_addon_version, warn):
    if min_addon_version >= OBSOLETE_FROM:
        warn("[LEGACY-1.9.5] MIN_ADDON_VERSION >= 1.9.6: legacy.py is dead code. Run: grep -rn \"LEGACY-1.9.5\" . and remove what it finds.")
