import unittest

import i18n


class I18nTest(unittest.TestCase):
    def test_language_from_header(self):
        self.assertEqual(i18n.language("de-DE,de;q=0.9,en;q=0.8"), "de")
        self.assertEqual(i18n.language("en-GB"), "en")
        self.assertEqual(i18n.language("fr-FR"), "en")     # unsupported -> English
        self.assertEqual(i18n.language(None), "en")

    def test_text_with_decimal_comma_in_german(self):
        self.assertEqual(i18n.text("pin_locked", "de", s=12), "Zu viele Fehlversuche – bitte 12 s warten.")
        self.assertIn("0.23 s", i18n.text("crossing_too_close", "en", gap=0.234))
        self.assertIn("0,23 s", i18n.text("crossing_too_close", "de", gap=0.234))

    def test_user_error(self):
        e = i18n.UserError("name_exists", name="Anna")
        self.assertIsInstance(e, ValueError)
        self.assertEqual(str(e), "“Anna” already exists.")
        self.assertEqual(e.text("de"), "„Anna“ gibt es schon.")

    def test_every_message_in_both_languages(self):
        for key, texts in i18n.MESSAGES.items():
            self.assertEqual(set(texts), set(i18n.LANGUAGES), key)


if __name__ == "__main__":
    unittest.main()
