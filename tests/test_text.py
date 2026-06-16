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

from slak.text import fold


def test_fold_lowercases_ascii():
    assert fold("HELLO") == "hello"


def test_fold_strips_accents():
    assert fold("Mélanie") == "melanie"


def test_fold_query_and_candidate_match_across_accents():
    assert fold("Café") == fold("cafe")


def test_fold_handles_multiple_diacritics():
    assert fold("naïve résumé") == "naive resume"


def test_fold_leaves_plain_ascii_identical_to_lowercase():
    s = "general-channel_42"
    assert fold(s) == s.lower()


def test_fold_preserves_non_latin_without_combining_marks():
    # Cyrillic has no decomposable combining marks here; should just lowercase.
    assert fold("ПРИВЕТ") == "привет"
