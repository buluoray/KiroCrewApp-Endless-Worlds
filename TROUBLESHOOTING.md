# Troubleshooting

Problems you might run into while playing Endless Worlds, and how to fix them.
(For developer/CI workflow, see [`CONTRIBUTING.md`](CONTRIBUTING.md).)

## The story stops advancing / the narrator won't respond

**What you see.** You make a choice and the turn never arrives — the page keeps
"thinking", or the app says it can't read your life and nothing happens.

**Why.** The narrator runs as an agent on your Kiro Crew gateway, and
occasionally a session comes up without Endless Worlds' tools attached, so it has
nothing to read or write the turn with. Your life and world are **not** lost —
this is a connection hiccup, not damage to your save.

**Fix: restart the gateway, then reopen Endless Worlds.** A restart re-attaches
the app to fresh sessions.

- **Desktop app:** quit it and open it again, then reopen Endless Worlds from the
  sidebar.
- **Running it as a background service or on another machine:** restart the Kiro
  Crew service (or ask whoever runs it to), then reload the dashboard.

Reopen your life and make the choice again — it's safe to retry; a turn is never
applied twice.

If it keeps happening right after a restart, make sure Endless Worlds is still
enabled in the app list, and reinstall/re-enable it if it isn't.

## A page shows a plain colored background instead of a picture

Some pages use a real photograph as the backdrop; others show a soft colored
gradient. A gradient instead of a photo is usually normal:

- Not every scene has a free-to-use photo (and stylized or fantasy worlds often
  have none), so those pages fall back to a colored backdrop by design — the
  story is unaffected.
- A one-off network hiccup can miss a photo; the app retries on its own, so it
  typically fixes itself on the next page.

If you **never** get photo backdrops on any world, the machine running your
gateway is probably missing the image tools the app needs to make them — see the
Install section of the [README](README.md), or ask whoever set up your gateway to
add them. Everything else in the app still works without them.

## The Life Star Map is blank or white

Close and reopen the star map, or reload the app. If it still comes up blank,
you're likely on an older build — update Endless Worlds to the latest version and
try again.

## You updated, but still see the old version

After an update, re-sync (or reinstall) Endless Worlds in your gateway so it picks
up the new version, then refresh the dashboard tab. If the page still looks old, a
hard refresh of the browser tab clears a cached copy.

## Endless Worlds isn't in the sidebar

It needs to be installed **and** enabled. Enable it from the gateway's app list
(or reinstall the app if it's missing), then reopen the dashboard.

## Still stuck?

When reporting a problem, it helps to say: which world/life you were in, exactly
what you saw on screen, and whether restarting the gateway changed anything.
