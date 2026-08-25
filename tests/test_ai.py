import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from talk_to_me.ai import TalkToMeAI, extract_question


class QuestionExtractionTests(unittest.TestCase):
    def test_separates_encouragement_from_question(self):
        self.assertEqual(
            extract_question("Nice answer! What music do you like?"),
            "What music do you like?",
        )

    def test_kie_chat_completion_response(self):
        settings = SimpleNamespace(
            kie_api_key="test", kie_chat_url="https://example.test/chat", kie_chat_model="test-model"
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "Hello!"}}]}
        with patch("talk_to_me.ai.requests.post", return_value=response):
            self.assertEqual(TalkToMeAI(settings)._chat_sync([{"role": "user", "content": "Hi"}]), "Hello!")

    def test_uses_last_question(self):
        self.assertEqual(
            extract_question("Do you like cats? Why do you like them?"),
            "Why do you like them?",
        )

    def test_keeps_plain_question(self):
        self.assertEqual(
            extract_question("What is your favorite animal?"),
            "What is your favorite animal?",
        )


if __name__ == "__main__":
    unittest.main()
