# MaagPaste

A clipboard history manager for Windows with a modern Windows 11 look, plus
your own account so everything you copy syncs live to a website too. It
watches your clipboard, saves every copy, and lets you browse and re-copy
anything from **Today, Yesterday, This Week, This Month, This Year,** or
**Older**.

## Notes

- Each account's clipboard history lives under `users/<their-uid>/` in the
  database — see the security rules section above to make sure that stays
  private to them.
- The global hotkey (`Ctrl+Alt+V`) uses the `keyboard` library, which on some
  systems needs the app run as Administrator to register system-wide. If it
  doesn't work, open MaagPaste from the tray icon instead.
- Right now it stores **text** clipboard content. Image clipboard support
  could be added later if you want it.
