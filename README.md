# slak

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-GPLv3-blue)

A terminal Slack client built on [Textual](https://textual.textualize.io/).

> Unofficial. Uses Slack's internal browser protocol and may violate Slack's TOS.
> Not affiliated with Slack Technologies, LLC.

## Features

**Keyboard-first.** Borderless Textual UI — workspace rail, channel sidebar, message
pane, compose. The compose box is focused on launch, so you just start typing. `Tab`
cycles focus, `Ctrl+P` opens the command palette (every action), and `F1` shows the
full keybinding reference.

**Workspaces & navigation**

- Multiple workspaces with concurrent live connections; `Alt+1`…`Alt+9` jump,
  `Ctrl+W` opens a filterable switcher.
- `Ctrl+K` fuzzy channel/DM finder — also lists public channels you haven't
  joined (marked `· join`) and joins one on selection; `Alt+←`/`Alt+→` walk
  channel history; `Ctrl+B` toggles the sidebar, `Ctrl+T` the thread panel.
- Drag the dividers between the channel list / messages / thread to resize them;
  the widths are remembered across restarts.
- Cache-first startup: your last context renders instantly while sync runs behind it.

**Messaging**

- Send, **edit** (`Ctrl+E`), and delete messages; reactions (`Ctrl+R`); threads with
  a follow-the-cursor reply panel.
- `Ctrl+N` new-message composer (DM and group DM); `@`/`:` mention & emoji
  autocomplete; `Ctrl+O` opens link(s) in a message; `Space` previews image attachments.
- In-channel (`Ctrl+F`) and workspace-wide (`Ctrl+Shift+F`) search.
- Typing indicators, both directions.

**Sidebar**

- Slack-native sections (`users.channelSections.list`, linked-list order) with a
  pinned `★ Starred` section, or config-glob sections (`[sections.<name>]`) as a
  fallback — grouped, collapsible, live-updated on section/star events.
- A `⚑ Threads` row opens the threads view (your subscribed threads, newest-reply
  first). DM and group-DM names are resolved to member display names.

**Rendering**

- Slack markdown, mentions, custom emoji (inline images on kitty), fenced code
  blocks (rendered literally on a tinted block), and Block Kit / legacy attachments
  (headers, sections, fields, context, dividers, controls).
- Inline images for files and attachments — kitty graphics on kitty, `▀` half-blocks
  on any truecolor terminal.
- `Space` previews the selected message's image full-screen. Default is an in-terminal
  preview (works over SSH); set `[appearance] image_preview = gui` to open it in an
  external viewer on the local machine instead.
- Colour themes (13 built-in incl. a true-black `oled` and terminal-following `ansi-dark`/`ansi-light`,
  plus `~/.config/slak/themes/*.toml` and `[theme]` overrides), switched live with
  `Ctrl+Y`; the sidebar is auto-kept contrasting (CIELAB).
- Optional **user avatars** beside messages (`[appearance] avatars = on`, off by
  default) — rendered as 4×2 half-blocks in a left gutter.
- Optional **coloured author names** (`[appearance] colored_names = true`, off by
  default) — each author name and `@mention` tinted by a deterministic hash of the
  user id.
- **Local nicknames** — `Ctrl+G` on a message renames its author just for you
  (stored by user id in `[nicknames]`); the nickname shows everywhere that name does.
- Optional **author grouping** (`[appearance] group_within_minutes = N`, 0 = off) —
  consecutive messages from the same author within N minutes drop the repeated
  name/timestamp header (and avatar), so a back-and-forth reads as a block.
- Private channels show a padlock — the single-width `` glyph when an installed
  font covers it (Nerd Font / FontAwesome, detected via fontconfig), else a narrow
  `⚿` fallback (`[appearance] nerd_font = auto|on|off`).

**Realtime & integration**

- RTM with exponential-backoff reconnection and missed-history backfill.
- Desktop notifications, presence/DND, terminal tab-title unread indicator.
- Opt-in embedded **MCP server** (`[mcp] enabled = true`) — an AI client reads your
  context (`slak_get_context`) and drafts a reply (`slak_set_draft`, draft-only).
  Run the adapter with `slak --mcp` (`pip install 'slak[mcp]'`).

Underneath: a pluggable `SlackClient` (browser-cookie auth, with an in-memory fake
for offline/dev), a self-healing SQLite cache (WAL + FTS5), and round-trippable TOML
config. ~340 tests.

Not yet wired: the sixel image protocol (half-blocks cover non-kitty terminals).

## Install

Recommended — [pipx](https://pipx.pypa.io) installs it isolated and puts `slak`
on your `PATH` globally:

```bash
pipx install slak
pipx install 'slak[mcp]'   # with the optional MCP adapter
```

Or with pip (ideally in a virtualenv):

```bash
pip install slak
```

### Debian / Ubuntu (.deb)

**Requires Ubuntu 24.04 (Noble) or newer** — slak needs Python ≥ 3.12, which
24.04 is the first Ubuntu LTS to ship (22.04 has 3.10 and is not supported).

A pre-built `.deb` is attached to each [release](https://github.com/Frodotus/slak/releases);
it bundles slak + all deps in a private venv under `/usr/lib/slak` and depends only
on `python3.12` (apt pulls it automatically):

```bash
sudo apt install ./slak_<version>_noble_amd64.deb
slak
```

To build one yourself (run on the same release you install on — the bundle is tied
to that release's Python minor version and CPU architecture):

```bash
packaging/build-deb.sh                  # -> dist/slak_<version>_<arch>.deb
sudo apt install ./dist/slak_*.deb
```

Remove with `sudo apt remove slak`.

### Nix

A flake is provided:

```bash
nix run github:Frodotus/slak     # run without installing
nix profile install github:Frodotus/slak
nix develop                       # dev shell with deps + pytest
```

Either way you get a `slak` command.

## First run

Just run it:

```bash
slak
```

On the first launch (no workspace configured yet) slak opens a short **setup
wizard** that walks you through copying your Slack browser session — an `xoxc-…`
token and the `d` cookie — from `https://app.slack.com` via DevTools. Credentials
are stored locally and sent only to Slack. After that, `slak` connects to your
workspace automatically.

```bash
slak                  # your workspace (runs the setup wizard on first launch)
slak --add-workspace  # run the wizard again to add another workspace
slak --list-workspaces
slak --demo           # explore a seeded demo workspace (no account needed)
```

(`slak` with no workspace in a non-interactive shell — CI/cron — prints setup
instructions and exits rather than prompting; use `--demo` there.)

## Develop

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

python -m slak --demo               # run against a seeded demo workspace
textual run --dev slak/dev.py       # run with live CSS hot-reload
textual console                      # (separate terminal) stream logs
pytest                               # run the test suite
```

The look is themeable CSS — edit `slak/ui/styles/app.tcss` while running under
`--dev` to restyle instantly.

## License

[GNU General Public License v3.0 or later](LICENSE).
