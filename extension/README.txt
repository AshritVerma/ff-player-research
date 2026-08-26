FF Research Draft Companion — Chrome extension
==============================================

Install once, then every ESPN draft room just works: no bookmark, no console
paste, no sink window.

INSTALL (about 30 seconds, once)
  1. Chrome → chrome://extensions
  2. Turn on "Developer mode" (top right)
  3. Click "Load unpacked"
  4. Select this folder:  ~/Code/ff-player-research/extension
  5. Done. It stays installed across restarts.

USE
  1. Start the helper:   python3 draft_sync.py --room-only
     (or plain `python3 draft_sync.py` for a real draft — it uses both sources)
  2. Open your ESPN draft room. A dark badge appears bottom-right reading
     "FF Research · N picks tracked". That's it.
  3. Open the dashboard and flip Live Draft.

The extension's toolbar icon also shows a green count of picks tracked, or a
red "!" if the helper isn't running.

WHY AN EXTENSION
Chrome refuses every request from an HTTPS page to a local HTTP server — fetch,
XHR and images alike. An extension service worker with host_permissions is
exempt, so picks go straight to the helper and the old sink-window workaround
is gone.

The bookmarklet still exists (bookmarklet_url.txt) as a fallback if you're on a
machine where you'd rather not install anything.
