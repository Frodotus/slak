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

"""Release guard: the pushed tag, pyproject version, and slak/version.py must agree.

Run in CI on a ``v*`` tag push; exits non-zero (failing the release) on mismatch.
"""

import os
import re
import sys
import tomllib

tag = os.environ.get("GITHUB_REF_NAME", "")
pyproject = tomllib.load(open("pyproject.toml", "rb"))["project"]["version"]
src = open("slak/version.py").read()
m = re.search(r'__version__\s*=\s*"([^"]+)"', src)
version_py = m.group(1) if m else "?"

errors = []
if tag != f"v{pyproject}":
    errors.append(f"tag {tag!r} != v{pyproject} (pyproject)")
if version_py != pyproject:
    errors.append(f"slak/version.py {version_py!r} != pyproject {pyproject!r}")

if errors:
    print("Version check failed:\n  " + "\n  ".join(errors), file=sys.stderr)
    sys.exit(1)
print(f"Version OK: {tag}")
