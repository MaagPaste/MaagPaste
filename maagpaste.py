"""
MaagPaste - A Windows 11 styled clipboard history manager with account sync.

Sign in, and every copy you make syncs live to your account and shows up
on the MaagPaste website in real time too. Logging out is always just one
click - no password needed. Your password is only ever asked for again to
open Settings, where you control whether deleting history is even allowed.

Author: built for Jake
"""

import os
import sys
import time
import sqlite3
import threading
from datetime import datetime, timedelta

import customtkinter as ctk
import pyperclip
import pystray
import keyboard
from PIL import Image, ImageDraw

import firebase_client as fb

APP_NAME = "MaagPaste"
ACCENT = "#0078D4"
BG_DARK = "#202020"
CARD_DARK = "#2b2b2b"
CARD_HOVER = "#333333"
TEXT_MUTED = "#9a9a9a"
ERROR_RED = "#e06c6c"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def app_data_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


DB_PATH = os.path.join(app_data_dir(), "history.db")


# ---------------------------------------------------------------------------
# Local storage (fast local cache; Firebase is the synced source of truth)
# ---------------------------------------------------------------------------

class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS history (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0
                )"""
            )
            self.conn.commit()

    def add(self, entry_id, content, created_at):
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO history (id, content, created_at, pinned) "
                "VALUES (?, ?, ?, COALESCE((SELECT pinned FROM history WHERE id=?), 0))",
                (entry_id, content, created_at, entry_id),
            )
            self.conn.commit()

    def all(self):
        with self.lock:
            cur = self.conn.execute(
                "SELECT id, content, created_at, pinned FROM history "
                "ORDER BY pinned DESC, created_at DESC"
            )
            return cur.fetchall()

    def delete(self, entry_id):
        with self.lock:
            self.conn.execute("DELETE FROM history WHERE id = ?", (entry_id,))
            self.conn.commit()

    def toggle_pin(self, entry_id):
        with self.lock:
            cur = self.conn.execute("SELECT pinned FROM history WHERE id = ?", (entry_id,))
            row = cur.fetchone()
            if row:
                self.conn.execute(
                    "UPDATE history SET pinned = ? WHERE id = ?",
                    (0 if row[0] else 1, entry_id),
                )
                self.conn.commit()

    def ids(self):
        with self.lock:
            return {r[0] for r in self.conn.execute("SELECT id FROM history")}

    def clear_all(self):
        with self.lock:
            self.conn.execute("DELETE FROM history WHERE pinned = 0")
            self.conn.commit()


GROUP_ORDER = ["Pinned", "Today", "Yesterday", "This Week", "This Month", "This Year", "Older"]


def group_for(dt):
    today = datetime.now().date()
    d = dt.date()
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    if d >= today - timedelta(days=today.weekday()):
        return "This Week"
    if d.year == today.year and d.month == today.month:
        return "This Month"
    if d.year == today.year:
        return "This Year"
    return "Older"


def friendly_time(dt):
    today = datetime.now().date()
    if dt.date() == today:
        return dt.strftime("%I:%M %p").lstrip("0")
    if dt.date() == today - timedelta(days=1):
        return "Yesterday, " + dt.strftime("%I:%M %p").lstrip("0")
    return dt.strftime("%b %d, %Y")


# ---------------------------------------------------------------------------
# Clipboard watcher
# ---------------------------------------------------------------------------

class ClipboardWatcher(threading.Thread):
    def __init__(self, on_new_copy):
        super().__init__(daemon=True)
        self.on_new_copy = on_new_copy
        self._last = None
        self._running = True
        self._suppress_until = 0

    def suppress_briefly(self):
        self._suppress_until = time.time() + 1.0

    def stop(self):
        self._running = False

    def run(self):
        try:
            self._last = pyperclip.paste()
        except Exception:
            self._last = None
        while self._running:
            try:
                current = pyperclip.paste()
            except Exception:
                current = None
            if current and current != self._last:
                self._last = current
                if time.time() >= self._suppress_until:
                    self.on_new_copy(current)
            time.sleep(0.5)


# ---------------------------------------------------------------------------
# Small reusable password dialog (masked input)
# ---------------------------------------------------------------------------

class PasswordDialog(ctk.CTkToplevel):
    def __init__(self, master, title, message):
        super().__init__(master)
        self.title(title)
        self.geometry("340x200")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)
        self.result = None
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(self, text=message, wraplength=280, font=ctk.CTkFont(size=13)).pack(
            padx=20, pady=(20, 10)
        )
        self.entry = ctk.CTkEntry(self, show="•", width=260, placeholder_text="Password")
        self.entry.pack(pady=6)
        self.entry.bind("<Return>", lambda e: self._submit())

        self.error_label = ctk.CTkLabel(self, text="", text_color=ERROR_RED, font=ctk.CTkFont(size=11))
        self.error_label.pack(pady=(0, 4))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=8)
        ctk.CTkButton(btns, text="Cancel", width=100, fg_color="transparent",
                      border_width=1, command=self._cancel).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Confirm", width=100, command=self._submit).pack(side="left", padx=6)

        self.entry.focus()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def show_error(self, msg):
        self.error_label.configure(text=msg)

    def _submit(self):
        self.result = self.entry.get()
        self.grab_release()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.grab_release()
        self.destroy()

    @staticmethod
    def ask(master, title, message):
        dialog = PasswordDialog(master, title, message)
        master.wait_window(dialog)
        return dialog.result


# ---------------------------------------------------------------------------
# Login screen
# ---------------------------------------------------------------------------

class LoginWindow(ctk.CTk):
    def __init__(self, on_success):
        super().__init__()
        self.on_success = on_success
        self.title("MaagPaste - Sign in")
        self.geometry("360x440")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)
        self.mode = "signin"
        self._build_ui()

    def _build_ui(self):
        for w in self.winfo_children():
            w.destroy()

        ctk.CTkLabel(self, text="MaagPaste", font=ctk.CTkFont(size=26, weight="bold")).pack(pady=(40, 4))
        subtitle = "Sign in to sync your clipboard" if self.mode == "signin" else "Create your account"
        ctk.CTkLabel(self, text=subtitle, text_color=TEXT_MUTED, font=ctk.CTkFont(size=13)).pack(pady=(0, 24))

        self.email_entry = ctk.CTkEntry(self, width=280, height=38, placeholder_text="Email",
                                         corner_radius=10, fg_color=CARD_DARK, border_width=0)
        self.email_entry.pack(pady=6)

        self.pass_entry = ctk.CTkEntry(self, width=280, height=38, placeholder_text="Password",
                                        show="•", corner_radius=10, fg_color=CARD_DARK, border_width=0)
        self.pass_entry.pack(pady=6)
        self.pass_entry.bind("<Return>", lambda e: self._submit())

        self.error_label = ctk.CTkLabel(self, text="", text_color=ERROR_RED,
                                         font=ctk.CTkFont(size=12), wraplength=280)
        self.error_label.pack(pady=(8, 0))

        action_text = "Sign In" if self.mode == "signin" else "Create Account"
        self.submit_btn = ctk.CTkButton(self, text=action_text, width=280, height=38,
                                         corner_radius=10, command=self._submit)
        self.submit_btn.pack(pady=(16, 10))

        toggle_text = ("Need an account? Create one" if self.mode == "signin"
                        else "Already have an account? Sign in")
        ctk.CTkButton(self, text=toggle_text, fg_color="transparent", hover_color=CARD_DARK,
                      text_color=ACCENT, command=self._toggle_mode).pack()

    def _toggle_mode(self):
        self.mode = "signup" if self.mode == "signin" else "signin"
        self._build_ui()

    def _submit(self):
        email = self.email_entry.get().strip()
        password = self.pass_entry.get()
        if not email or not password:
            self.error_label.configure(text="Enter both an email and a password.")
            return
        self.submit_btn.configure(state="disabled", text="Please wait…")
        self.error_label.configure(text="")
        threading.Thread(target=self._do_auth, args=(email, password), daemon=True).start()

    def _do_auth(self, email, password):
        try:
            if self.mode == "signin":
                session = fb.sign_in(email, password)
            else:
                session = fb.sign_up(email, password)
        except fb.FirebaseError as e:
            self.after(0, lambda: self._auth_failed(str(e)))
            return
        except Exception:
            self.after(0, lambda: self._auth_failed("Couldn't reach the server. Check your internet connection."))
            return
        self.after(0, lambda: self._auth_succeeded(session))

    def _auth_failed(self, message):
        self.submit_btn.configure(state="normal", text="Sign In" if self.mode == "signin" else "Create Account")
        self.error_label.configure(text=message)

    def _auth_succeeded(self, session):
        self.destroy()
        self.on_success(session)


# ---------------------------------------------------------------------------
# Entry card widget
# ---------------------------------------------------------------------------

class EntryCard(ctk.CTkFrame):
    def __init__(self, master, entry_id, content, created_at, pinned,
                 on_copy, on_delete, on_pin, delete_allowed, **kwargs):
        super().__init__(master, fg_color=CARD_DARK, corner_radius=10, **kwargs)
        self.entry_id = entry_id
        self.content = content
        self.grid_columnconfigure(0, weight=1)

        preview = content.strip().replace("\n", "  ")
        if len(preview) > 120:
            preview = preview[:120] + "…"

        text_label = ctk.CTkLabel(self, text=preview, anchor="w", justify="left",
                                   font=ctk.CTkFont(size=13), text_color="#f2f2f2", wraplength=280)
        text_label.grid(row=0, column=0, sticky="ew", padx=(14, 8), pady=(10, 2))

        meta = f"{friendly_time(created_at)}   ·   {len(content)} chars"
        meta_label = ctk.CTkLabel(self, text=meta, anchor="w", font=ctk.CTkFont(size=11), text_color=TEXT_MUTED)
        meta_label.grid(row=1, column=0, sticky="ew", padx=(14, 8), pady=(0, 10))

        pin_btn = ctk.CTkButton(self, text="📌" if pinned else "📍", width=30, height=30, corner_radius=8,
                                 fg_color="transparent", hover_color=CARD_HOVER, font=ctk.CTkFont(size=13),
                                 command=lambda: on_pin(entry_id))
        pin_btn.grid(row=0, column=1, rowspan=2, padx=(0, 4), pady=8)

        if delete_allowed:
            del_btn = ctk.CTkButton(self, text="✕", width=30, height=30, corner_radius=8,
                                     fg_color="transparent", hover_color="#4a2020", text_color="#d98686",
                                     font=ctk.CTkFont(size=13), command=lambda: on_delete(entry_id))
            del_btn.grid(row=0, column=2, rowspan=2, padx=(0, 10), pady=8)

        for widget in (self, text_label, meta_label):
            widget.bind("<Button-1>", lambda e: on_copy(content))
            widget.bind("<Enter>", lambda e: self.configure(fg_color=CARD_HOVER))
            widget.bind("<Leave>", lambda e: self.configure(fg_color=CARD_DARK))


# ---------------------------------------------------------------------------
# Settings dialog (password-gated to open)
# ---------------------------------------------------------------------------

class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Settings")
        self.geometry("340x260")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(self, text="Settings", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(20, 4))
        ctk.CTkLabel(self, text=app.session.email, text_color=TEXT_MUTED,
                     font=ctk.CTkFont(size=12)).pack(pady=(0, 16))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(row, text="Allow deleting history", font=ctk.CTkFont(size=13)).pack(side="left")
        self.switch_var = ctk.BooleanVar(value=app.allow_delete)
        switch = ctk.CTkSwitch(row, text="", variable=self.switch_var, command=self._save)
        switch.pack(side="right")

        ctk.CTkButton(self, text="Log out", fg_color="transparent", border_width=1,
                      border_color="#3a3a3a", hover_color=CARD_DARK,
                      command=self._logout).pack(pady=(24, 8))

        ctk.CTkButton(self, text="Close", command=self.destroy).pack()

    def _save(self):
        self.app.set_allow_delete(self.switch_var.get())

    def _logout(self):
        self.destroy()
        self.app.logout()


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class MaagPasteApp:
    def __init__(self, session):
        self.session = session
        self.db = Database(DB_PATH)
        self.allow_delete = True
        self._syncing_ids = set()

        self.root = ctk.CTk()
        self.root.title("MaagPaste")
        self.root.geometry("400x640")
        self.root.minsize(340, 420)
        self.root.configure(fg_color=BG_DARK)
        self._set_icon()

        self._build_ui()
        self._load_remote_settings()
        self._pull_remote(initial=True)

        self.watcher = ClipboardWatcher(self._on_new_copy)
        self.watcher.start()

        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.tray_icon = None
        self._setup_tray()
        self._setup_hotkey()
        self._start_poll_loop()

    # -- chrome -----------------------------------------------------------

    def _set_icon(self):
        try:
            base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base_path, "icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

    def _build_ui(self):
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(header, text="MaagPaste", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")

        gear_btn = ctk.CTkButton(header, text="⚙", width=32, height=28, corner_radius=8,
                                  fg_color="transparent", border_width=1, border_color="#3a3a3a",
                                  hover_color=CARD_HOVER, font=ctk.CTkFont(size=13),
                                  command=self.open_settings)
        gear_btn.pack(side="right")

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.refresh())
        search_entry = ctk.CTkEntry(self.root, textvariable=self.search_var,
                                     placeholder_text="Search clipboard history…", height=36,
                                     corner_radius=10, fg_color=CARD_DARK, border_width=0)
        search_entry.pack(fill="x", padx=16, pady=(0, 10))

        self.scroll = ctk.CTkScrollableFrame(self.root, fg_color="transparent",
                                              scrollbar_button_color="#3a3a3a",
                                              scrollbar_button_hover_color="#4a4a4a")
        self.scroll.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.status_label = ctk.CTkLabel(self.root, text=f"Signed in as {self.session.email}",
                                          text_color=TEXT_MUTED, font=ctk.CTkFont(size=10))
        self.status_label.pack(pady=(0, 8))

    # -- remote settings ----------------------------------------------------

    def _load_remote_settings(self):
        def work():
            try:
                settings = fb.get_settings(self.session)
                self.allow_delete = settings.get("allow_delete", True)
                self.root.after(0, self.refresh)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def set_allow_delete(self, value):
        self.allow_delete = value
        self.refresh()
        threading.Thread(target=lambda: self._safe(
            fb.set_settings, self.session, {"allow_delete": value}
        ), daemon=True).start()

    def open_settings(self):
        pw = PasswordDialog.ask(self.root, "Confirm password",
                                 "Enter your password to open Settings.")
        if pw is None:
            return
        try:
            fb.verify_password(self.session.email, pw)
        except fb.FirebaseError:
            self._toast("Incorrect password.")
            return
        except Exception:
            self._toast("Couldn't reach the server.")
            return
        SettingsDialog(self.root, self)

    # -- rendering ----------------------------------------------------------

    def refresh(self):
        for widget in self.scroll.winfo_children():
            widget.destroy()

        rows = self.db.all()
        query = self.search_var.get().strip().lower()
        if query:
            rows = [r for r in rows if query in r[1].lower()]

        if not rows:
            empty_label = ctk.CTkLabel(
                self.scroll, text="Nothing copied yet.\nStart copying — it'll show up here.",
                text_color=TEXT_MUTED, font=ctk.CTkFont(size=13), justify="center",
            )
            empty_label.pack(pady=60)
            return

        groups = {}
        for entry_id, content, created_at, pinned in rows:
            dt = datetime.fromisoformat(created_at)
            label = "Pinned" if pinned else group_for(dt)
            groups.setdefault(label, []).append((entry_id, content, dt, pinned))

        for label in GROUP_ORDER:
            if label not in groups:
                continue
            header = ctk.CTkLabel(self.scroll, text=label.upper(), font=ctk.CTkFont(size=11, weight="bold"),
                                   text_color=ACCENT, anchor="w")
            header.pack(fill="x", padx=6, pady=(10, 4))
            for entry_id, content, dt, pinned in groups[label]:
                card = EntryCard(self.scroll, entry_id, content, dt, pinned,
                                  on_copy=self.copy_entry, on_delete=self.delete_entry,
                                  on_pin=self.pin_entry, delete_allowed=self.allow_delete)
                card.pack(fill="x", pady=4)

    # -- clipboard capture + sync --------------------------------------------

    def _on_new_copy(self, content):
        entry_id = str(int(time.time() * 1000))
        created_at = datetime.now().isoformat()
        self.db.add(entry_id, content, created_at)
        self.root.after(0, self.refresh)
        self._syncing_ids.add(entry_id)
        threading.Thread(target=self._push_one, args=(entry_id, content, created_at), daemon=True).start()

    def _push_one(self, entry_id, content, created_at):
        try:
            fb.push_entry(self.session, entry_id, content, created_at)
        except Exception:
            pass
        finally:
            self._syncing_ids.discard(entry_id)

    def _pull_remote(self, initial=False):
        try:
            remote = fb.fetch_all(self.session)
        except Exception:
            return
        local_ids = self.db.ids()
        remote_ids = set(remote.keys())

        for entry_id, data in remote.items():
            if entry_id not in local_ids:
                self.db.add(entry_id, data.get("content", ""), data.get("created_at", datetime.now().isoformat()))

        for entry_id in local_ids - remote_ids:
            if entry_id in self._syncing_ids:
                continue  # not pushed yet, don't treat as a remote deletion
            self.db.delete(entry_id)

        self.root.after(0, self.refresh)

    def _start_poll_loop(self):
        def loop():
            while True:
                time.sleep(5)
                self._pull_remote()
        threading.Thread(target=loop, daemon=True).start()

    # -- actions --------------------------------------------------------------

    def copy_entry(self, content):
        self.watcher.suppress_briefly()
        pyperclip.copy(content)

    def delete_entry(self, entry_id):
        if not self.allow_delete:
            self._toast("Deleting is turned off in Settings.")
            return
        self.db.delete(entry_id)
        self.refresh()
        threading.Thread(target=lambda: self._safe(fb.delete_entry, self.session, entry_id), daemon=True).start()

    def pin_entry(self, entry_id):
        self.db.toggle_pin(entry_id)
        self.refresh()

    def _safe(self, fn, *args):
        try:
            fn(*args)
        except Exception:
            pass

    def _toast(self, message):
        self.status_label.configure(text=message)
        self.root.after(2500, lambda: self.status_label.configure(text=f"Signed in as {self.session.email}"))

    # -- window show/hide -------------------------------------------------

    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        self.refresh()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def toggle_window(self):
        if self.root.state() == "withdrawn":
            self.show_window()
        else:
            self.hide_window()

    def logout(self):
        self.watcher.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        try:
            keyboard.remove_hotkey("ctrl+alt+v")
        except Exception:
            pass
        self.root.destroy()
        start_app()  # back to the login screen

    # -- tray ---------------------------------------------------------------

    def _tray_image(self):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, 63, 63], radius=14, fill=(0, 120, 212, 255))
        d.rounded_rectangle([16, 12, 48, 52], radius=6, fill=(255, 255, 255, 255))
        d.rounded_rectangle([24, 8, 40, 18], radius=4, fill=(0, 120, 212, 255))
        return img

    def _setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open MaagPaste", lambda: self.root.after(0, self.show_window), default=True),
            pystray.MenuItem("Log out", lambda: self.root.after(0, self.logout)),
            pystray.MenuItem("Quit", self._quit),
        )
        self.tray_icon = pystray.Icon(APP_NAME, self._tray_image(), APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _setup_hotkey(self):
        try:
            keyboard.add_hotkey("ctrl+alt+v", lambda: self.root.after(0, self.toggle_window))
        except Exception:
            pass

    def _quit(self):
        self.watcher.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    def run(self):
        self.root.mainloop()


def start_app():
    def on_login(session):
        app = MaagPasteApp(session)
        app.run()

    login = LoginWindow(on_login)
    login.mainloop()


if __name__ == "__main__":
    start_app()
