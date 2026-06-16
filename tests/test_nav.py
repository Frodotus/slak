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

from slak.nav import NavHistory


def test_starts_empty():
    h = NavHistory()
    assert h.current() is None
    assert h.back() is None
    assert h.forward() is None


def test_visit_sets_current_without_back():
    h = NavHistory()
    h.visit("C1")
    assert h.current() == "C1"
    assert h.back() is None  # nothing before the first visit


def test_back_and_forward_walk_the_stack():
    h = NavHistory()
    h.visit("C1")
    h.visit("C2")
    h.visit("C3")
    assert h.back() == "C2"
    assert h.back() == "C1"
    assert h.back() is None  # at the start
    assert h.forward() == "C2"
    assert h.forward() == "C3"
    assert h.forward() is None  # at the end


def test_visiting_after_back_truncates_forward():
    h = NavHistory()
    h.visit("C1")
    h.visit("C2")
    h.visit("C3")
    assert h.back() == "C2"
    h.visit("C9")  # new navigation from C2
    assert h.current() == "C9"
    assert h.forward() is None  # C3 was truncated
    assert h.back() == "C2"


def test_revisiting_current_is_a_noop():
    h = NavHistory()
    h.visit("C1")
    h.visit("C1")
    assert h.back() is None
    assert h.current() == "C1"


def test_back_skips_stale_channels():
    h = NavHistory()
    h.visit("C1")
    h.visit("C2")
    h.visit("C3")
    # C2 no longer exists; back from C3 should skip it and land on C1
    assert h.back(valid={"C1", "C3"}) == "C1"


def test_forward_skips_stale_channels():
    h = NavHistory()
    h.visit("C1")
    h.visit("C2")
    h.visit("C3")
    h.back()  # -> C2
    h.back()  # -> C1
    # C2 gone; forward from C1 should skip it and land on C3
    assert h.forward(valid={"C1", "C3"}) == "C3"
