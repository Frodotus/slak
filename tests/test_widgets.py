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

from slak.slack import Reaction, RemoteMessage
from slak.ui.widgets import MessagePane


def _pane() -> MessagePane:
    pane = MessagePane()
    pane._name_of = lambda u: u
    return pane


def test_reaction_pill_renders_custom_as_text_and_standard_as_glyph():
    m = RemoteMessage(
        "1.0", "u", "hi",
        reactions=[Reaction("thisisfine", 2, ["x"]), Reaction("+1", 1, ["y"])],
    )
    body = _pane()._body(m)
    assert ":thisisfine:" in body   # custom reaction -> text (no kitty placeholder)
    assert "👍" in body              # standard reaction -> glyph
    assert "[dim]2[/dim]" in body    # only the count is dimmed


def test_reaction_emoji_helper():
    pane = _pane()
    assert pane._reaction_emoji("thisisfine") == ":thisisfine:"
    assert pane._reaction_emoji("+1") == "👍"


def test_private_channel_glyph_nerd_vs_fallback():
    from slak.slack import RemoteChannel
    from slak.ui.widgets import _channel_glyph, set_private_glyph

    priv = RemoteChannel("C1", "secret", "private")
    try:
        set_private_glyph(True)
        assert _channel_glyph(priv) == ""          # Nerd padlock
        set_private_glyph(False)
        assert _channel_glyph(priv) == "🔒"      # fallback lock
        assert _channel_glyph(RemoteChannel("C2", "general", "channel")) == "#"
        assert _channel_glyph(RemoteChannel("D1", "bob", "dm")) == "●"
    finally:
        set_private_glyph(True)  # restore default for other tests
