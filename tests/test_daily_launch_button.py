import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

from cogs import daily


class DailyLaunchButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_view_is_persistent(self):
        view = daily.DailyLaunchView()

        self.assertIsNone(view.timeout)
        self.assertEqual(len(view.children), 1)
        button = view.children[0]
        self.assertEqual(button.custom_id, "daily_guessr:launch")
        self.assertEqual(button.label, "Jouer")

    async def test_button_launches_activity_for_current_daily(self):
        response = SimpleNamespace(launch_activity=AsyncMock())
        interaction = SimpleNamespace(
            guild_id=99,
            user=SimpleNamespace(id=42),
            response=response,
        )
        view = daily.DailyLaunchView()

        with (
            mock.patch.object(daily, "is_allowed", return_value=True),
            mock.patch.object(daily.database, "get_daily", return_value={"ok": True}),
            mock.patch.object(daily, "global_name", return_value="Player One"),
            mock.patch.object(daily, "_user_avatar_url", return_value=""),
            mock.patch.object(daily.database, "upsert_user") as upsert_user,
        ):
            await view.children[0].callback(interaction)

        response.launch_activity.assert_awaited_once_with()
        upsert_user.assert_called_once_with(99, 42, "Player One", "")


if __name__ == "__main__":
    unittest.main()
