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

from slak.render import render_message


def name_of(uid: str) -> str:
    return {"U1": "Alice", "U2": "Bob"}.get(uid, uid)


def r(text: str) -> str:
    return render_message(text, name_of)


def test_user_mention_resolved():
    assert r("hi <@U1>") == "hi @Alice"


def test_user_mention_coloured_when_color_of_given():
    color = {"U1": "#aabbcc"}.get   # U1 has a colour, U2 -> None
    out = render_message("hi <@U1> and <@U2>", name_of, color_of=color)
    assert "[#aabbcc]@Alice[/]" in out   # U1 tinted by its colour
    assert "]@Bob" not in out            # U2 left plain
    assert "@Bob" in out


def test_user_mention_plain_without_color_of():
    assert "[#" not in render_message("hi <@U1>", name_of)  # default: no colour


def test_unknown_user_uses_label_then_id():
    assert r("<@U9|carol>") == "@carol"
    assert r("<@U9>") == "@U9"


def test_channel_reference():
    assert r("see <#C2|general> please") == "see #general please"


def test_broadcasts():
    assert r("<!here> heads up") == "@here heads up"
    assert r("<!subteam^S1|@team> ping") == "@team ping"


def test_links_render_as_clickable_hyperlinks():
    # OSC 8 hyperlink markup (URL quoted); look (underline/colour) is CSS link-*
    assert r("<https://x.io|the site>") == '[link="https://x.io"]the site[/link]'
    assert r("<https://x.io>") == '[link="https://x.io"]https://x.io[/link]'


def test_link_url_keeps_query_after_html_unescape():
    # Slack escapes & in URLs; the link target must use the real &
    assert r("<https://x.io?a=1&amp;b=2>") == \
        '[link="https://x.io?a=1&b=2"]https://x.io?a=1&b=2[/link]'


def test_html_entities_unescaped():
    assert r("a &amp; b &lt;tag&gt;") == "a & b <tag>"


def test_standard_emoji_rendered_custom_left_as_text():
    assert r("yo :wave:") == "yo 👋"
    assert r("lol :thisisfine:") == "lol :thisisfine:"   # custom emoji has no glyph


def test_markup_injection_is_neutralised():
    # a message that looks like markup must not be interpreted — every '[' is
    # backslash-escaped (Textual content markup treats '[' as a tag opener, and
    # even '[0]' / '[$1]' would be mis-parsed)
    assert r("[b]hax[/b]") == "\\[b]hax\\[/b]"
    assert r("arr[0] = x") == "arr\\[0] = x"


def test_brackets_parse_cleanly_as_textual_markup():
    # the real-world crash: SQL with [$1::DATE … $2::UUID] must render, not raise
    from textual.content import Content

    out = render_message("set due=[$1::DATE, id=$2::UUID]", name_of)
    content = Content.from_markup(out)  # must not raise MarkupError
    assert content.plain == "set due=[$1::DATE, id=$2::UUID]"


def test_bold_and_italic_become_rich_markup():
    assert r("*hi* _there_") == "[b]hi[/b] [i]there[/i]"


def _chip(name):
    return f"[reverse]:{name}:[/reverse]" if name == "thisisfine" else None


def test_custom_render_callback_used_for_known_custom():
    out = render_message("lol :thisisfine:", name_of, _chip)
    assert out == "lol [reverse]:thisisfine:[/reverse]"


def test_custom_render_none_leaves_shortcode_plain():
    assert render_message("lol :nope:", name_of, _chip) == "lol :nope:"
