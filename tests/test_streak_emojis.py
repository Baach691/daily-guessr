import unittest

from cogs.daily import loss_streak_emoji, streak_emoji


class StreakEmojiTests(unittest.TestCase):
    def test_win_emojis_keep_old_tiers_and_change_every_five(self):
        expected = {
            0: "🧊",
            2: "🔥",
            5: "🚀",
            10: "💎",
            15: "✨",
            20: "👑",
            25: "☢️",
            30: "🌟",
            35: "🏆",
            40: "🪐",
            45: "🌌",
            50: "♾️",
        }
        self.assertEqual(
            {value: streak_emoji(value) for value in expected},
            expected,
        )

    def test_loss_emojis_keep_old_tiers_and_change_every_five(self):
        expected = {
            1: "🥶",
            2: "📉",
            5: "💀",
            10: "⚰️",
            15: "🕳️",
            20: "🌋",
            25: "☠️",
            30: "🚨",
            35: "🧨",
            40: "🪦",
            45: "🫥",
            50: "🌑",
        }
        self.assertEqual(
            {value: loss_streak_emoji(value) for value in expected},
            expected,
        )


if __name__ == "__main__":
    unittest.main()
