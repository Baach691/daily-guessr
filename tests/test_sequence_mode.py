import json
import os
import re
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import config
import database
import filters
import tokens
from cogs.daily import today_str
from webapp import server


class _FakeUpstream:
    status = 200
    headers = {
        "Content-Type": "image/jpeg",
        "Content-Length": "4",
        "Accept-Ranges": "bytes",
    }

    def __init__(self):
        self._chunks = [b"test", b""]

    def read(self, _size):
        return self._chunks.pop(0)

    def close(self):
        pass


class SequenceModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = config.DB_PATH
        self.original_secret = config.WEBAPP_SECRET
        config.DB_PATH = os.path.join(self.tmp.name, "test.db")
        config.WEBAPP_SECRET = "sequence-test-secret"
        if database._conn is not None:
            database._conn.close()
        database._conn = None
        database.init_db()

        self.date = today_str()
        self.messages = [
            {
                "id": str(message_id),
                "author_id": str(100 + index),
                "author_name": f"Joueur {index + 1}",
                "content": f"Message {index + 1}",
                "has_media": index == 0,
                "media_url": (
                    "https://cdn.discordapp.com/attachments/20/100/old.jpg"
                    if index == 0 else ""
                ),
                "media_is_video": False,
            }
            for index, message_id in enumerate(range(100, 105))
        ]
        database.create_sequence_daily_if_absent(
            1,
            self.date,
            20,
            self.messages,
        )
        self.app = server.create_app()
        self.app.testing = True

    def tearDown(self):
        if database._conn is not None:
            database._conn.close()
        database._conn = None
        config.DB_PATH = self.original_db_path
        config.WEBAPP_SECRET = self.original_secret
        self.tmp.cleanup()

    def _token(self, user_id=30):
        return tokens.make_token(
            {
                "g": 1,
                "u": user_id,
                "d": self.date,
                "n": f"Joueur {user_id}",
                "a": "",
                "m": database.MODE_SEQUENCE,
            },
            config.WEBAPP_SECRET,
        )

    def test_page_contains_five_messages_in_a_stable_shuffled_order(self):
        token = self._token()
        with self.app.test_client() as client:
            first = client.get(f"/daily?t={token}").get_data(as_text=True)
            second = client.get(f"/daily?t={token}").get_data(as_text=True)

        first_order = re.findall(r'data-message-id="(\d+)"', first)
        second_order = re.findall(r'data-message-id="(\d+)"', second)
        canonical = [message["id"] for message in self.messages]
        self.assertEqual(len(first_order), 5)
        self.assertEqual(first_order, second_order)
        self.assertCountEqual(first_order, canonical)
        self.assertNotEqual(first_order, canonical)
        self.assertIn("Valider l'ordre", first)
        self.assertIn("Classement</h2>", first)
        self.assertIn("Joue pour débloquer le classement", first)

    def test_correct_order_records_partial_score_leaderboard_points(self):
        token = self._token()
        correct_order = [message["id"] for message in self.messages]
        with self.app.test_client() as client:
            client.post(
                "/daily/start",
                json={"token": token, "difficulty": "hardcore"},
            )
            response = client.post(
                "/daily/answer",
                json={"token": token, "guess_order": correct_order},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["correct"])
        self.assertEqual(payload["guessed_id"], "5")
        self.assertEqual(payload["correct_order"], correct_order)
        self.assertEqual(payload["difficulty"], "normal")
        self.assertEqual(payload["leaderboard"][0]["points"], 5)
        self.assertTrue(payload["leaderboard"][0]["played_today"])

        leaderboard = database.get_leaderboard(1, mode=database.MODE_SEQUENCE)
        self.assertEqual(leaderboard[0]["points"], 5)
        self.assertEqual(leaderboard[0]["correct"], 1)
        self.assertEqual(leaderboard[0]["total"], 1)

    def test_wrong_order_records_exact_positions(self):
        token = self._token(31)
        reverse_order = [message["id"] for message in reversed(self.messages)]
        with self.app.test_client() as client:
            response = client.post(
                "/daily/answer",
                json={"token": token, "guess_order": reverse_order},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["correct"])
        self.assertEqual(response.get_json()["guessed_id"], "1")
        attempt = database.get_daily_attempt(
            1,
            self.date,
            31,
            mode=database.MODE_SEQUENCE,
        )
        self.assertEqual(attempt["guessed_order"], reverse_order)
        self.assertEqual(
            database.get_leaderboard(1, mode=database.MODE_SEQUENCE)[0]["points"],
            1,
        )

    def test_result_keeps_guess_and_shows_correct_order_without_drag_handles(self):
        token = self._token(32)
        wrong_order = ["101", "102", "103", "104", "100"]
        with self.app.test_client() as client:
            answer = client.post(
                "/daily/answer",
                json={"token": token, "guess_order": wrong_order},
            )
            page = client.get(f"/daily?t={token}").get_data(as_text=True)

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.get_json()["guessed_id"], "0")
        self.assertIn("Ton ordre", page)
        self.assertIn("Bon ordre", page)
        self.assertIn("<strong>0/5</strong>", page)
        self.assertNotIn("sequence-handle", page)
        self.assertNotIn("sequence-result-mark correct", page)
        self.assertEqual(page.count("sequence-result-mark wrong"), 5)
        guessed_section = page.split("Ton ordre", 1)[1].split("Bon ordre", 1)[0]
        self.assertEqual(
            re.findall(r'data-message-id="(\d+)"', guessed_section),
            wrong_order,
        )

    def test_duplicate_or_foreign_message_is_rejected(self):
        token = self._token()
        with self.app.test_client() as client:
            response = client.post(
                "/daily/answer",
                json={
                    "token": token,
                    "guess_order": ["100", "100", "101", "102", "999"],
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "bad_sequence_order")
        self.assertIsNone(database.get_daily_attempt(
            1,
            self.date,
            30,
            mode=database.MODE_SEQUENCE,
        ))

    def test_sequence_media_is_proxied_only_for_a_challenge_message(self):
        fresh_url = "https://cdn.discordapp.com/attachments/20/100/fresh.jpg"
        with (
            mock.patch.object(
                server,
                "fetch_current_media_url",
                return_value=fresh_url,
            ),
            mock.patch.object(
                server.urllib.request,
                "urlopen",
                return_value=_FakeUpstream(),
            ),
            self.app.test_client() as client,
        ):
            valid = client.get(
                f"/daily/sequence/media?t={self._token()}&mid=100"
            )
            invalid = client.get(
                f"/daily/sequence/media?t={self._token()}&mid=101"
            )

        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.data, b"test")
        self.assertEqual(invalid.status_code, 404)

    def test_sequence_filter_rejects_bots_and_accepts_real_media(self):
        attachment = SimpleNamespace(
            content_type="image/png",
            filename="photo.png",
            url="https://cdn.discordapp.com/attachments/1/2/photo.png",
        )
        human = SimpleNamespace(
            bot=False,
            name="Joueur",
            global_name="Joueur",
            display_name="Joueur",
        )
        base = {
            "author": human,
            "webhook_id": None,
            "attachments": [attachment],
            "embeds": [],
            "content": "",
        }
        self.assertTrue(filters.is_sequence_eligible(
            SimpleNamespace(**base),
            config.MIN_CHARS,
            config.MIN_WORDS,
        ))
        bot_message = dict(base)
        bot_message["author"] = SimpleNamespace(
            bot=True,
            name="Bot",
            global_name="Bot",
            display_name="Bot",
        )
        self.assertFalse(filters.is_sequence_eligible(
            SimpleNamespace(**bot_message),
            config.MIN_CHARS,
            config.MIN_WORDS,
        ))


if __name__ == "__main__":
    unittest.main()
