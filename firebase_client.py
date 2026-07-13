"""
Thin REST client for Firebase Authentication + Realtime Database.
Plain HTTPS calls only (no firebase-admin SDK) so this packages cleanly
into a single-file exe with PyInstaller.
"""

import time
import requests

API_KEY = "AIzaSyCnDgLCSegRmRF4cDYMEkTVAfIQUrm9XWE"
DB_URL = "https://servicechat-f49d3-default-rtdb.firebaseio.com"

AUTH_BASE = "https://identitytoolkit.googleapis.com/v1/accounts"
TOKEN_URL = "https://securetoken.googleapis.com/v1/token"


class FirebaseError(Exception):
    pass


class Session:
    """Holds a signed-in user's tokens and refreshes them as needed."""

    def __init__(self, id_token, refresh_token, uid, email, expires_in):
        self.id_token = id_token
        self.refresh_token = refresh_token
        self.uid = uid
        self.email = email
        self.expires_at = time.time() + int(expires_in) - 60

    def ensure_fresh(self):
        if time.time() < self.expires_at:
            return
        resp = requests.post(
            TOKEN_URL, params={"key": API_KEY},
            data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
            timeout=10,
        )
        data = resp.json()
        if resp.status_code != 200:
            raise FirebaseError(data.get("error", {}).get("message", "Token refresh failed"))
        self.id_token = data["id_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = time.time() + int(data["expires_in"]) - 60


def _auth_call(endpoint, email, password):
    resp = requests.post(
        f"{AUTH_BASE}:{endpoint}", params={"key": API_KEY},
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=10,
    )
    data = resp.json()
    if resp.status_code != 200:
        raise FirebaseError(_friendly_error(data))
    return Session(data["idToken"], data["refreshToken"], data["localId"], email, data["expiresIn"])


def _friendly_error(data):
    code = data.get("error", {}).get("message", "AUTH_FAILED")
    mapping = {
        "EMAIL_EXISTS": "An account with that email already exists.",
        "EMAIL_NOT_FOUND": "No account found with that email.",
        "INVALID_PASSWORD": "Incorrect password.",
        "INVALID_LOGIN_CREDENTIALS": "Incorrect email or password.",
        "WEAK_PASSWORD : Password should be at least 6 characters": "Password must be at least 6 characters.",
        "INVALID_EMAIL": "That doesn't look like a valid email.",
    }
    return mapping.get(code, code.replace("_", " ").title())


def sign_up(email, password):
    return _auth_call("signUp", email, password)


def sign_in(email, password):
    return _auth_call("signInWithPassword", email, password)


def verify_password(email, password):
    """Re-auth check before sensitive actions. Raises FirebaseError if wrong."""
    sign_in(email, password)


def push_entry(session: Session, entry_id, content, created_at):
    session.ensure_fresh()
    url = f"{DB_URL}/users/{session.uid}/history/{entry_id}.json"
    resp = requests.put(
        url, params={"auth": session.id_token},
        json={"content": content, "created_at": created_at},
        timeout=10,
    )
    if resp.status_code != 200:
        raise FirebaseError(f"Sync failed: {resp.text}")


def delete_entry(session: Session, entry_id):
    session.ensure_fresh()
    url = f"{DB_URL}/users/{session.uid}/history/{entry_id}.json"
    resp = requests.delete(url, params={"auth": session.id_token}, timeout=10)
    if resp.status_code != 200:
        raise FirebaseError(f"Delete sync failed: {resp.text}")


def fetch_all(session: Session):
    session.ensure_fresh()
    url = f"{DB_URL}/users/{session.uid}/history.json"
    resp = requests.get(url, params={"auth": session.id_token}, timeout=10)
    if resp.status_code != 200:
        raise FirebaseError(f"Fetch failed: {resp.text}")
    return resp.json() or {}


def push_screen_frame(session: Session, b64_jpeg):
    session.ensure_fresh()
    url = f"{DB_URL}/users/{session.uid}/screen.json"
    resp = requests.put(
        url, params={"auth": session.id_token},
        json={"frame": b64_jpeg, "active": True, "ts": time.time()},
        timeout=10,
    )
    if resp.status_code != 200:
        raise FirebaseError(f"Screen push failed: {resp.text}")


def set_screen_inactive(session: Session):
    session.ensure_fresh()
    url = f"{DB_URL}/users/{session.uid}/screen/active.json"
    requests.put(url, params={"auth": session.id_token}, json=False, timeout=10)


def get_settings(session: Session):
    session.ensure_fresh()
    url = f"{DB_URL}/users/{session.uid}/settings.json"
    resp = requests.get(url, params={"auth": session.id_token}, timeout=10)
    if resp.status_code != 200:
        raise FirebaseError(f"Settings fetch failed: {resp.text}")
    return resp.json() or {"allow_delete": True}


def set_settings(session: Session, settings: dict):
    session.ensure_fresh()
    url = f"{DB_URL}/users/{session.uid}/settings.json"
    resp = requests.put(url, params={"auth": session.id_token}, json=settings, timeout=10)
    if resp.status_code != 200:
        raise FirebaseError(f"Settings save failed: {resp.text}")
