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

    slak                     run (real workspace if a token exists, else demo)
    slak --demo              force the seeded demo workspace
    slak --add-workspace     paste xoxc token + d cookie to add a workspace
    slak --list-workspaces   list configured workspaces
    slak --diagnose          print terminal image protocol + custom-emoji status
    slak --mcp               run the stdio MCP adapter (bridges to a running slak)
"""

from __future__ import annotations

import argparse
import asyncio
import os
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


async def add_workspace_flow() -> None:
    print("Add a Slack workspace using a browser session.")
    print("In your browser dev tools, copy the workspace token and `d` cookie.\n")
    access = input("xoxc token: ").strip()
    cookie = input("d cookie value: ").strip()
    info = await fetch_team_info(access, cookie)
    tok = token_from_auth_test(info, access, cookie)
    save_token(tok)
    print(f"\n✓ Saved {tok.team_name} ({tok.team_id}) at {tok.team_domain}.slack.com")


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
        asyncio.run(add_workspace_flow())
        return
    if args.list_workspaces:
        list_workspaces()
        return
    if args.diagnose:
        asyncio.run(diagnose())
        return

    cfg = load_config()
    from slak.themes import load_theme_files
    load_theme_files(THEMES_DIR)  # user themes override built-ins by name
    tokens = load_tokens()
    if args.demo or not tokens:
        router = WorkspaceRouter.single(demo_client())
        cache = Cache.open(":memory:")
        config_path = None  # don't let a demo session rewrite the real config
    else:
        clients = [HttpSlackClient(t) for t in tokens]
        order = cfg.order_team_ids([t.team_id for t in tokens])
        # honour default_workspace by making it active
        router = WorkspaceRouter(clients, order)
        default = pick_token(tokens, cfg).team_id
        router.set_active(default)
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache = Cache.open(str(CACHE_PATH))
        config_path = CONFIG_PATH

    PyslkApp(router=router, cache=cache, config=cfg, config_path=config_path).run()


if __name__ == "__main__":
    main()
