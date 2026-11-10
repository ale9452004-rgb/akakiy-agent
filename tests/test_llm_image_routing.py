import unittest
from unittest.mock import MagicMock, patch
from tools.agent import Agent

class TestLLMImageRouting(unittest.TestCase):
    def setUp(self):
        self.mock_ai = MagicMock()
        self.mock_ai.model = "qwen3:8b"
        self.mock_ai.send_chat = MagicMock()
        self.mock_ai.ask = MagicMock()

    def test_llm_image_routing_generates_image_call(self):
        agent = Agent(ai_client=self.mock_ai, enable_llm_image_routing=True)
        # Mock LLM response with tool_call to generate_image
        self.mock_ai.send_chat.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "generate_image",
                            "arguments": {
                                "prompt": "single cat, playing with soccer ball on grass football field, masterpiece",
                                "width": 1024,
                                "height": 1024
                            }
                        }
                    }
                ]
            },
            {
                "content": "Вот ваше изображение кота с футбольным мячом на поле!",
                "tool_calls": []
            }
        ]

        with patch.object(agent, "execute_tool", return_value={"success": True, "created_files": ["img_test.png"]}) as mock_exec:
            res = agent.process("Сгенерируй кота с футбольным мячом на футбольном поле")
            self.assertEqual(res.get("type"), "chat")
            self.assertIn("img_test.png", res.get("created_files", []))
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            self.assertEqual(args[0], "generate_image")
            self.assertIn("soccer ball", args[1]["prompt"])

    def test_llm_image_routing_edits_image_with_protect_bbox(self):
        agent = Agent(ai_client=self.mock_ai, enable_llm_image_routing=True)
        # Mock LLM response with tool_call to edit_image
        self.mock_ai.send_chat.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "edit_image",
                            "arguments": {
                                "prompt": "Mordor fortress, Sauron dark tower, dark fantasy volcano sky",
                                "edit_type": "background",
                                "protect_bbox": [0.2, 0.2, 0.8, 0.9],
                                "invert_mask": True
                            }
                        }
                    }
                ]
            },
            {
                "content": "Фон успешно заменён на замок Саурона с сохранением кота!",
                "tool_calls": []
            }
        ]

        with patch.object(agent, "execute_tool", return_value={"success": True, "created_files": ["img_edited.png"]}) as mock_exec:
            res = agent.process("Отредактируй изображение, поменяй фон на замок Саурона")
            self.assertEqual(res.get("type"), "chat")
            self.assertIn("img_edited.png", res.get("created_files", []))
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            self.assertEqual(args[0], "edit_image")
            self.assertEqual(args[1]["edit_type"], "background")
            self.assertEqual(args[1]["protect_bbox"], [0.2, 0.2, 0.8, 0.9])
            self.assertTrue(args[1]["invert_mask"])

if __name__ == "__main__":
    unittest.main()
