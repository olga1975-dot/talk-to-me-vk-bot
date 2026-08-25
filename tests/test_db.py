import tempfile
import unittest
from pathlib import Path

from talk_to_me.db import Database


class DatabaseTests(unittest.TestCase):
    def test_profile_and_history_persist(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(str(Path(folder) / "test.db"))
            p = db.get_profile(7)
            p.name, p.age, p.level, p.interests = "Sam", 11, "A2", "games"
            db.save_profile(p)
            db.add_message(7, "user", "I like games.")
            self.assertTrue(db.get_profile(7).complete)
            self.assertEqual(db.history(7, 5)[0]["content"], "I like games.")


if __name__ == "__main__":
    unittest.main()
