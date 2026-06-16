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

from slak.cache import Cache, Message
from slak.slack import (
    FakeSlackClient,
    MessageDeleted,
    MessageEdited,
    RemoteMessage,
)


async def test_fake_update_message_changes_text_and_emits_event():
    c = FakeSlackClient(history={"C1": [RemoteMessage("1.0", "Uself", "old")]})
    await c.update_message("C1", "1.0", "new text")
    assert (await c.history("C1"))[0].text == "new text"
    ev = await c.next_event()
    assert isinstance(ev, MessageEdited)
    assert (ev.channel_id, ev.ts, ev.text) == ("C1", "1.0", "new text")


async def test_fake_delete_message_removes_and_emits_event():
    c = FakeSlackClient(history={"C1": [RemoteMessage("1.0", "Uself", "bye")]})
    await c.delete_message("C1", "1.0")
    assert await c.history("C1") == []
    ev = await c.next_event()
    assert isinstance(ev, MessageDeleted)
    assert (ev.channel_id, ev.ts) == ("C1", "1.0")


def test_cache_delete_message_hides_it():
    cache = Cache.open(":memory:")
    cache.add_message(
        Message(ts="1.0", channel_id="C1", workspace_id="T1", user_id="U", text="hi")
    )
    assert len(cache.get_messages("C1")) == 1
    cache.delete_message("C1", "1.0")
    assert cache.get_messages("C1") == []
