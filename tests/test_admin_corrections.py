import json
import os
import tempfile
import unittest
from unittest import mock

import config
import database


class AdminCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = config.DB_PATH
        config.DB_PATH = os.path.join(self.tmp.name, "test.db")
        if database._conn is not None:
            database._conn.close()
        database._conn = None
        database.init_db()

    def tearDown(self):
        if database._conn is not None:
            database._conn.close()
        database._conn = None
        config.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def _seed_mode(self, mode):
        conn = database.get_conn()
        options = json.dumps([[100, "Bonne réponse"], [200, "Mauvaise réponse"]])
        if mode == database.MODE_SEQUENCE:
            messages = json.dumps([
                {
                    "id": str(message_id),
                    "author_id": "100",
                    "author_name": "Joueur",
                    "content": f"Message {message_id}",
                    "has_media": False,
                    "media_url": "",
                    "media_is_video": False,
                }
                for message_id in range(1, 6)
            ])
            for daily_date in ("2026-06-25", "2026-06-26"):
                conn.execute(
                    "INSERT INTO sequence_daily "
                    "(guild_id, date, channel_id, first_message_id, messages) "
                    "VALUES (1, ?, 50, 1, ?)",
                    (daily_date, messages),
                )
        elif mode == database.MODE_PHRASE:
            conn.execute(
                "INSERT INTO phrase_daily "
                "(guild_id, date, target_author_id, target_author_name, "
                " correct_message_id, channel_id, content, options) "
                "VALUES (1, '2026-06-25', 999, 'Cible', 100, 50, 'Phrase', ?)",
                (options,),
            )
            conn.execute(
                "INSERT INTO phrase_daily "
                "(guild_id, date, target_author_id, target_author_name, "
                " correct_message_id, channel_id, content, options) "
                "VALUES (1, '2026-06-26', 999, 'Cible', 100, 50, 'Phrase', ?)",
                (options,),
            )
        else:
            daily_table = "daily" if mode == database.MODE_AUTHOR else "media_daily"
            conn.execute(
                f"INSERT INTO {daily_table} "
                "(guild_id, date, message_id, channel_id, author_id, author_name, "
                " content, options) VALUES (1, '2026-06-25', 1, 50, 100, "
                "'Bonne réponse', 'Contenu', ?)",
                (options,),
            )
            conn.execute(
                f"INSERT INTO {daily_table} "
                "(guild_id, date, message_id, channel_id, author_id, author_name, "
                " content, options) VALUES (1, '2026-06-26', 2, 50, 100, "
                "'Bonne réponse', 'Contenu', ?)",
                (options,),
            )

        attempts = database._tbl(mode, "daily_attempts")
        correct_guess = 5 if mode == database.MODE_SEQUENCE else 100
        wrong_guess = 0 if mode == database.MODE_SEQUENCE else 200
        second_difficulty = (
            "hardcore"
            if mode in (database.MODE_AUTHOR, database.MODE_MEDIA)
            else "normal"
        )
        conn.execute(
            f"INSERT INTO {attempts} "
            "(guild_id, date, user_id, user_name, guessed_id, correct, answered_at, "
            " time_taken_ms, difficulty) "
            "VALUES (1, '2026-06-25', 10, 'Joueur', ?, 1, "
            "'2026-06-25 12:00:00', 1000, 'normal')",
            (correct_guess,),
        )
        conn.execute(
            f"INSERT INTO {attempts} "
            "(guild_id, date, user_id, user_name, guessed_id, correct, answered_at, "
            " time_taken_ms, difficulty) "
            "VALUES (1, '2026-06-26', 10, 'Joueur', ?, 0, "
            "'2026-06-26 12:00:00', 2000, ?)",
            (wrong_guess, second_difficulty),
        )
        conn.commit()
        database.recompute_player_stats(mode)

    def test_correction_recomputes_all_four_modes(self):
        for mode in database.VALID_MODES:
            with self.subTest(mode=mode):
                self._seed_mode(mode)
                corrected_guess = 5 if mode == database.MODE_SEQUENCE else 100
                result = database.correct_daily_attempt(
                    1, "2026-06-26", 10, corrected_guess, mode=mode
                )

                self.assertIsNotNone(result)
                self.assertTrue(result["correct"])
                leaderboard = database.get_leaderboard(1, mode=mode)
                self.assertEqual(leaderboard[0]["correct"], 2)
                self.assertEqual(leaderboard[0]["total"], 2)
                expected_points = (
                    10
                    if mode == database.MODE_SEQUENCE
                    else 3
                    if mode in (database.MODE_AUTHOR, database.MODE_MEDIA)
                    else 2
                )
                self.assertEqual(leaderboard[0]["points"], expected_points)
                self.assertEqual(leaderboard[0]["current_streak"], 2)
                self.assertEqual(leaderboard[0]["best_streak"], 2)
                self.assertEqual(leaderboard[0]["current_loss_streak"], 0)

    def test_correction_can_turn_a_win_into_a_loss(self):
        self._seed_mode(database.MODE_AUTHOR)
        result = database.correct_daily_attempt(
            1, "2026-06-25", 10, 0, mode=database.MODE_AUTHOR
        )

        self.assertFalse(result["correct"])
        leaderboard = database.get_leaderboard(1, mode=database.MODE_AUTHOR)
        self.assertEqual(leaderboard[0]["correct"], 0)
        self.assertEqual(leaderboard[0]["total"], 2)
        self.assertEqual(leaderboard[0]["points"], 0)
        self.assertEqual(leaderboard[0]["current_streak"], 0)
        self.assertEqual(leaderboard[0]["current_loss_streak"], 2)

    def test_correction_rolls_back_if_recompute_fails(self):
        self._seed_mode(database.MODE_AUTHOR)
        with mock.patch.object(
            database,
            "_recompute_player_stats_in_transaction",
            side_effect=RuntimeError("recompute failed"),
        ):
            with self.assertRaises(RuntimeError):
                database.correct_daily_attempt(
                    1, "2026-06-26", 10, 100, mode=database.MODE_AUTHOR
                )

        attempt = database.get_daily_attempt(
            1, "2026-06-26", 10, mode=database.MODE_AUTHOR
        )
        self.assertEqual(attempt["guessed_id"], 200)
        self.assertFalse(attempt["correct"])


if __name__ == "__main__":
    unittest.main()
