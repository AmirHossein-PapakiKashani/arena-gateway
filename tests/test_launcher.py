import unittest
from arena_gateway.arena_gemini import build_settings


class LauncherTests(unittest.TestCase):
    def test_custom_arena_models_are_visible_and_pinned(self):
        config = build_settings({"general": {"preferredEditor": "vscode"}}, ["gemini-4-argon-high", "gpt-6-luna-max"], "gpt-6-luna-max")
        self.assertEqual(config["general"]["preferredEditor"], "vscode")
        self.assertTrue(config["experimental"]["dynamicModelConfiguration"])
        self.assertEqual(config["model"]["name"], "gpt-6-luna-max")
        self.assertTrue(config["modelConfigs"]["modelDefinitions"]["gpt-6-luna-max"]["isVisible"])
        self.assertEqual(config["modelConfigs"]["aliases"]["chat-base"]["modelConfig"]["model"], "gpt-6-luna-max")

    def test_unavailable_model_is_rejected(self):
        with self.assertRaises(ValueError):
            build_settings({}, ["gemini-4-argon-high"], "gpt-5.5")
