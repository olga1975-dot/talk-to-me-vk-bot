import unittest

from talk_to_me.guardrails import check_answer


class GuardrailTests(unittest.TestCase):
    def test_child_under_ten_can_use_one_word(self):
        self.assertTrue(check_answer("Cats", 8).accepted)

    def test_older_child_needs_sentence(self):
        result = check_answer("Rammstein", 10)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "short")

    def test_sentence_is_accepted(self):
        self.assertTrue(check_answer("I would play Rammstein.", 10).accepted)

    def test_consonant_gibberish_is_rejected(self):
        self.assertEqual(check_answer("sdfghjkl", 8).reason, "nonsense")

    def test_repeated_letters_are_rejected(self):
        self.assertEqual(check_answer("aaaaaaa", 8).reason, "nonsense")

    def test_unsafe_topic_is_rejected(self):
        self.assertEqual(check_answer("I want vodka", 12).reason, "unsafe")


if __name__ == "__main__":
    unittest.main()
