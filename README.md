# slak

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-GPLv3-blue)

A modern, **non-modal** terminal Slack client built on [Textual](https://textual.textualize.io/).

> Unofficial. Uses Slack's internal browser protocol and may violate Slack's TOS.
> Not affiliated with Slack Technologies, LLC.

## Status

Early MVP scaffold. Working today:

- Borderless Textual shell — workspace rail, channel sidebar, message pane, compose.
- **Non-modal:** compose is focused on launch — just type. `Tab` moves focus; the
  command palette is `Ctrl+P`.
- Pluggable `SlackClient` interface with an in-memory **fake** (boots with zero
  credentials) and a real **`HttpSlackClient`** (browser-cookie auth → Web API:
  channels, history, send; RTM realtime feed).
- Token store (`slak --add-workspace`, `--list-workspaces`), SQLite cache
  (messages + read-state), config (theme resolution + workspace ordering + slugs),
  accent-insensitive matching.

- Multi-workspace switching (`Alt+1`…`Alt+9`), **`Ctrl+K` fuzzy channel finder**,
  **`F1` keyboard-shortcut help**, threads, reactions (with inline custom-emoji
  images on kitty), in-channel and workspace search, `@`/`:` autocomplete,
  desktop notifications, presence/DND.

- `Ctrl+B` toggles the sidebar; `Ctrl+T` toggles the thread panel.

- `Ctrl+W` opens a filterable workspace switcher (beyond the `Alt+1`…`Alt+9` jumps);
  `Alt+←`/`Alt+→` walk channel history back/forward.

- `Ctrl+O` opens link(s) in the selected message (picker when there's more than one).
- `Ctrl+E` edits your selected message; "Delete message" (palette) removes it.
- `Ctrl+Y` picks a colour theme for the active workspace (`Ctrl+Shift+Y` sets the
  default); ~10 built-in themes so far, applied live with no restart.
- `Ctrl+N` starts a new message — filter users, `Tab` to add several (group DM),
  `Enter` to open the DM.

- Theme picks persist to `~/.config/slak/config.toml` (real workspaces; the demo
  never rewrites your config).
- A `⚑ Threads` sidebar row opens the **threads view** — your subscribed threads,
  newest-reply first; the side panel follows the cursor.
- **Sidebar sections** via config globs (`[sections.<name>] patterns = [...]`,
  per-workspace override) — grouped, collapsible channel headers.
- **Reconnect backfill** — on RTM reconnect, fetches each channel's missed history
  (4-wide pool, deduped per workspace) and refreshes threads/the open channel.
- **Block Kit & legacy attachments** — bot/app messages (`blocks`/`attachments`)
  render as headers, sections + field grids, context, dividers, and muted control
  labels, instead of being dropped.
- **Embedded MCP server** (opt-in, `[mcp] enabled = true`) — an AI client can read
  your current context (`slak_get_context`) and draft a reply into the composer
  (`slak_set_draft`, draft-only — you review and send). Adapter: `slak --mcp`
  (needs `pip install 'slak[mcp]'`).

Not yet wired: Slack-native sections / stars, the full ~70-theme set, inline
block images. See the spec set for the full roadmap.

## Use a real workspace

```bash
slak --add-workspace      # paste your browser xoxc token + d cookie
slak                      # connects to it (falls back to demo if no token)
slak --demo               # always use the seeded demo workspace
```

## Develop

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

python -m slak                      # run against a seeded demo workspace
textual run --dev slak/dev.py       # run with live CSS hot-reload
textual console                      # (separate terminal) stream logs
pytest                               # run the test suite
```

The look is themeable CSS — edit `slak/ui/styles/app.tcss` while running under
`--dev` to restyle instantly.

## License

[GNU General Public License v3.0 or later](LICENSE).
