from slak.app import PyslkApp
from slak.cache import Cache
from slak.config import Config
from slak.slack import FakeSlackClient, RemoteChannel, RemoteMessage
from slak.ui.widgets import MessagePane
from slak.workspace import WorkspaceRouter


async def test_message_with_replies_renders_without_error():
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "u", "parent", reply_count=3)]},
    )
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        pane = app.query_one("#messages", MessagePane)
        # the rendered Static must paint cleanly (accent markup resolves)
        line = str(pane._widgets[-1].render())
        assert "3 replies" in line
