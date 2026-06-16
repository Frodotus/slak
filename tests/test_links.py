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

from slak.links import extract_links


def test_no_links():
    assert extract_links("just some plain text") == []


def test_angle_wrapped_link():
    assert extract_links("see <https://example.com>") == ["https://example.com"]


def test_labeled_link_keeps_url_not_label():
    assert extract_links("<https://example.com|Example site>") == [
        "https://example.com"
    ]


def test_bare_url():
    assert extract_links("ship it https://foo.bar/x now") == ["https://foo.bar/x"]


def test_trailing_punctuation_is_trimmed_on_bare_urls():
    assert extract_links("docs at https://foo.bar/x.") == ["https://foo.bar/x"]


def test_multiple_links_in_document_order():
    text = "first <https://a.com|A> then https://b.com and <https://c.com>"
    assert extract_links(text) == ["https://a.com", "https://b.com", "https://c.com"]


def test_duplicates_collapsed_keeping_first():
    text = "<https://a.com> again https://a.com"
    assert extract_links(text) == ["https://a.com"]
