# MaagPaste

A clipboard history manager for Windows with a modern Windows 11 look, plus
your own account so everything you copy syncs live to a website too. It
watches your clipboard, saves every copy, and lets you browse and re-copy
anything from **Today, Yesterday, This Week, This Month, This Year,** or
**Older**.

## Features

- 🕒 Automatic clipboard capture, grouped by date
- 🔍 Instant search across everything you've ever copied
- 📌 Pin important entries so they never get lost
- 🖱️ Click any entry to copy it straight back to your clipboard
- 🗂️ Runs in the system tray — open it anytime with **Ctrl+Alt+V**
- 🎨 Dark, rounded, Windows 11–style UI (built with CustomTkinter)
- 🔐 Your own account (Firebase Auth) — sign up, sign in, **log out anytime
  with one click, no password needed**
- 🌐 Live-synced website — watch your clipboard history appear in real time
  from any browser, on the account only you can log into
- ⚙️ Settings are password-gated to open, and inside them **you** control
  whether deleting history is even allowed on your account

## One-time setup: Firebase security rules

The app and website both use the Firebase project config you provided. Before
using it for real, lock down the database so each account can only read and
write **its own** data — otherwise any signed-in user could read anyone
else's clipboard history. In the [Firebase console](https://console.firebase.google.com/)
→ your project → **Realtime Database → Rules**, set:

```json
{
  "rules": {
    "users": {
      "$uid": {
        ".read": "$uid === auth.uid",
        ".write": "$uid === auth.uid"
      }
    }
  }
}
```

Click **Publish**. Without this, the database defaults may allow broader
access than you want.

## Run from source

```bash
pip install -r requirements.txt
python maagpaste.py
```

## Build the .exe

PyInstaller has to compile on an actual Windows machine — it can't be
cross-built from Mac/Linux. There are two ways to get `MaagPaste.exe`:

### Option A — Let GitHub build it for you (no Windows machine needed)

This repo includes a GitHub Actions workflow (`.github/workflows/build.yml`)
that builds the exe on a real Windows server every time you push.

1. Push this repo to GitHub (see below).
2. Go to your repo's **Actions** tab — a "Build MaagPaste.exe" run should
   already be in progress (or click **Run workflow** to trigger it manually).
3. When it finishes, open the run and download the **MaagPaste-exe** artifact
   — that's your `.exe`.
4. For a permanent download link instead of a build artifact, tag a version:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
   The workflow will attach `MaagPaste.exe` to a Release on that tag.

### Option B — Build it locally on Windows

```bash
build.bat
```

Produces `dist\MaagPaste.exe` — a single double-clickable file, no Python
installation needed on the machine that runs it.

### Optional: launch on Windows startup

1. Press `Win + R`, type `shell:startup`, hit Enter.
2. Copy a shortcut to `MaagPaste.exe` into that folder.
3. MaagPaste will now start (minimized to tray) every time you log in.

## Publishing to GitHub

From inside the `MaagPaste` folder:

```bash
git init
git add .
git commit -m "Initial commit: MaagPaste clipboard history app"
git branch -M main
git remote add origin https://github.com/<your-username>/MaagPaste.git
git push -u origin main
```

## The website

The live web dashboard lives in its own repo, **MaagPaste-Web**, so this repo
stays focused on just the desktop app. Both share the same Firebase project,
so signing in on one shows the same account and clipboard history as the
other. See that repo's README for setup and hosting (GitHub Pages).

## Project structure

```
MaagPaste/
├── maagpaste.py         # desktop app
├── firebase_client.py   # Firebase Auth + Realtime Database REST client
├── requirements.txt
├── build.bat            # one-click Windows build
├── icon.ico
├── .github/workflows/build.yml   # auto-builds the exe on GitHub
├── .gitignore
└── README.md
```

The web dashboard lives separately in **MaagPaste-Web**.

## How the account system works

- **Sign in / sign up** — real accounts via Firebase Authentication.
- **Logging out is always one click**, from the tray menu or the app/site —
  no password required to leave your own session.
- **Settings are locked behind your password** — opening Settings re-checks
  your password against Firebase before showing anything. Inside, a single
  toggle controls whether deleting history is allowed at all on your account.
  If it's off, delete buttons simply don't do anything (in the app they're
  hidden entirely; on the site they're hidden too).
- **Sync is two-way** — copy something on your PC and it appears on the
  website within a few seconds; delete something on the website and it
  disappears from the app the same way.

## Notes

- Each account's clipboard history lives under `users/<their-uid>/` in the
  database — see the security rules section above to make sure that stays
  private to them.
- The global hotkey (`Ctrl+Alt+V`) uses the `keyboard` library, which on some
  systems needs the app run as Administrator to register system-wide. If it
  doesn't work, open MaagPaste from the tray icon instead.
- Right now it stores **text** clipboard content. Image clipboard support
  could be added later if you want it.
