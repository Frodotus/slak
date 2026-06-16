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

from types import SimpleNamespace

from slak.finder import rank_by_name


def ch(name: str):
    return SimpleNamespace(id=name, name=name, type="public")


def names(result):
    return [c.name for c in result]


def test_empty_query_returns_all_in_recency_order():
    chans = [ch("zebra"), ch("alpha"), ch("middle")]
    assert names(rank_by_name(chans, "")) == ["zebra", "alpha", "middle"]


def test_whitespace_query_is_treated_as_empty():
    chans = [ch("zebra"), ch("alpha")]
    assert names(rank_by_name(chans, "   ")) == ["zebra", "alpha"]


def test_non_matching_channels_are_excluded():
    chans = [ch("general"), ch("random"), ch("design")]
    assert names(rank_by_name(chans, "xyz")) == []


def test_match_tiers_exact_prefix_substring_subsequence():
    # "gen": exact=general?no. Use query "des".
    chans = [
        ch("undesirable"),  # substring (des inside)
        ch("design"),       # prefix
        ch("des"),          # exact
        ch("dauntless-eng-staging"),  # subsequence d..e..s
    ]
    assert names(rank_by_name(chans, "des")) == [
        "des",
        "design",
        "undesirable",
        "dauntless-eng-staging",
    ]


def test_within_tier_preserves_recency_order():
    chans = [ch("eng-platform"), ch("eng-web"), ch("eng-data")]
    # all are prefix matches for "eng"; original order is preserved
    assert names(rank_by_name(chans, "eng")) == [
        "eng-platform",
        "eng-web",
        "eng-data",
    ]


def test_match_is_case_insensitive():
    chans = [ch("General")]
    assert names(rank_by_name(chans, "gen")) == ["General"]


def test_match_is_accent_insensitive():
    chans = [ch("Café-eng")]
    assert names(rank_by_name(chans, "cafe")) == ["Café-eng"]


def test_subsequence_match():
    chans = [ch("general")]
    assert names(rank_by_name(chans, "grl")) == ["general"]
