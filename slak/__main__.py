# slak — Terminal Slack client
# Copyright (C) 2026 Toni Leino
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""slak entry point + workspace CLI.

    slak                     run a real workspace; first run opens the setup wizard
    slak --demo              force the seeded demo workspace
    slak --add-workspace     run the setup wizard to add a workspace
    slak --list-workspaces   list configured workspaces
    slak --diagnose          print terminal image protocol + custom-emoji status
    slak --mcp               run the stdio MCP adapter (bridges to a running slak)
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

from slak.app import PyslkApp
from slak.cache import Cache
from slak.config import Config
from slak.images import detect_protocol
from slak.slack import Token, demo_client
from slak.slack.http import HttpSlackClient, fetch_team_info, token_from_auth_test
from slak.slack.tokens import load_tokens, save_token
from slak.workspace import WorkspaceRouter

CONFIG_PATH = Path.home() / ".config" / "slak" / "config.toml"
CACHE_PATH = Path.home() / ".local" / "share" / "slak" / "cache.db"
THEMES_DIR = Path.home() / ".config" / "slak" / "themes"


def load_config() -> Config:
    if CONFIG_PATH.exists():
        return Config.loads(CONFIG_PATH.read_text())
    return Config()


def pick_token(tokens: list[Token], cfg: Config) -> Token:
    if cfg.default_workspace:
        for ws in cfg.workspaces:
            if ws.slug == cfg.default_workspace and ws.team_id:
                for t in tokens:
                    if t.team_id == ws.team_id:
                        return t
    return tokens[0]


_WIZARD_INTRO = """\
Let's connect a Slack workspace.

slak signs in with your existing browser session — an `xoxc-…` token and the `d`
cookie from the Slack web app. You copy these once; they're stored locally and
sent only to Slack.

  1. Open https://app.slack.com in your browser and sign in.
  2. Open DevTools (F12, or Ctrl/Cmd+Shift+I).
  3. TOKEN — in the Console tab, run:
         JSON.parse(localStorage.localConfig_v2).teams
     expand your workspace and copy its "token" value (starts with xoxc-).
  4. COOKIE — Application ▸ Cookies ▸ https://app.slack.com — copy the value of
     the cookie named `d` (starts with xoxd-).
"""

_NO_WORKSPACE_HINT = (
    "No Slack workspace configured. Add one with:\n"
    "    slak --add-workspace\n"
    "or try the bundled demo workspace:\n"
    "    slak --demo"
)


async def onboarding_wizard() -> bool:
    """Guide the user through adding a workspace (token + cookie). Returns True
    once a workspace is saved, False if they give up. Used on first run and for
    ``slak --add-workspace``."""
    print(_WIZARD_INTRO)
    for _ in range(3):
        access = input("Paste xoxc token: ").strip()
        cookie = getpass.getpass("Paste d cookie (hidden): ").strip()
        if not access or not cookie:
            print("Both the token and the cookie are required.\n")
            continue
        try:
            info = await fetch_team_info(access, cookie)
            tok = token_from_auth_test(info, access, cookie)
        except Exception as exc:
            print(f"✗ Couldn't verify those credentials ({exc}). Try again.\n")
            continue
        save_token(tok)
        print(f"\n✓ Connected {tok.team_name} ({tok.team_domain}.slack.com).")
        return True
    print("\nGave up after 3 attempts — no workspace was added.")
    return False


def startup_mode(has_tokens: bool, demo: bool, interactive: bool) -> str:
    """Decide how to launch: 'demo', 'real', 'wizard', or 'no-token'."""
    if demo:
        return "demo"
    if has_tokens:
        return "real"
    return "wizard" if interactive else "no-token"


def list_workspaces() -> None:
    tokens = load_tokens()
    if not tokens:
        print("No workspaces. Add one with: slak --add-workspace")
        return
    for t in tokens:
        print(f"{t.team_id}\t{t.team_name}\t{t.team_domain}.slack.com")


async def diagnose() -> None:
    print("=== terminal ===")
    print("detected image protocol:", detect_protocol(dict(os.environ)))
    for var in ("TERM", "TERM_PROGRAM", "KITTY_WINDOW_ID", "COLORTERM"):
        print(f"  {var} = {os.environ.get(var)!r}")
    print("=== custom emoji ===")
    tokens = load_tokens()
    if not tokens:
        print("no workspaces configured")
        return
    tok = pick_token(tokens, load_config())
    client = HttpSlackClient(tok)
    try:
        customs = await client.list_custom_emoji()
    except Exception as exc:
        print(f"emoji.list FAILED: {exc!r}")
        return
    finally:
        await client.aclose()
    print(f"workspace: {tok.team_name} ({tok.team_domain})")
    print(f"custom emoji fetched: {len(customs)}")
    for name in list(customs)[:10]:
        print(f"  :{name}: -> {customs[name][:70]}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="slak")
    parser.add_argument("--add-workspace", action="store_true")
    parser.add_argument("--list-workspaces", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument(
        "--mcp", action="store_true",
        help="run the stdio MCP adapter that bridges to a running slak",
    )
    args = parser.parse_args()

    if args.mcp:
        from slak.mcp import default_socket_path
        from slak.mcp.adapter import run_adapter

        run_adapter(load_config().mcp_socket_path or default_socket_path())
        return

    if args.add_workspace:
        sys.exit(0 if asyncio.run(onboarding_wizard()) else 1)
    if args.list_workspaces:
        list_workspaces()
        return
    if args.diagnose:
        asyncio.run(diagnose())
        return

    cfg = load_config()
    from slak.themes import load_theme_files
    load_theme_files(THEMES_DIR)  # user themes override built-ins by name

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    mode = startup_mode(bool(load_tokens()), args.demo, interactive)
    if mode == "wizard":
        if not asyncio.run(onboarding_wizard()):
            print("\n" + _NO_WORKSPACE_HINT, file=sys.stderr)
            sys.exit(1)
        mode = "real"  # a workspace was just added
    elif mode == "no-token":
        print(_NO_WORKSPACE_HINT, file=sys.stderr)
        sys.exit(1)

    _run_app(cfg, demo=(mode == "demo"))


def _run_app(cfg: Config, demo: bool) -> None:
    if demo:
        router = WorkspaceRouter.single(demo_client())
        cache = Cache.open(":memory:")
        config_path = None  # don't let a demo session rewrite the real config
    else:
        tokens = load_tokens()
        clients = [HttpSlackClient(t) for t in tokens]
        order = cfg.order_team_ids([t.team_id for t in tokens])
        # honour default_workspace by making it active
        router = WorkspaceRouter(clients, order)
        router.set_active(pick_token(tokens, cfg).team_id)
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache = Cache.open(str(CACHE_PATH))
        config_path = CONFIG_PATH

    PyslkApp(router=router, cache=cache, config=cfg, config_path=config_path).run()


if __name__ == "__main__":
    main()
