import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import playwright_chrome as app


class ConsoleTests(unittest.TestCase):
    def test_windows_paths_survive_console_parsing(self):
        path = r"C:\Users\Jean Francois\scenarios\outlook.json"
        self.assertEqual(app.split_console_command('executer --fichier "' + path + '"'),
                         ["executer", "--fichier", path])

    def test_json_option_works_after_action(self):
        output = io.StringIO()
        with patch.object(app, "list_recipes", return_value={"scenarios": []}), redirect_stdout(output):
            app.main(["lister", "--json"])
        self.assertEqual(json.loads(output.getvalue()), {"scenarios": []})

    def test_console_list_is_readable(self):
        output = io.StringIO()
        with redirect_stdout(output):
            app.print_result({"scenarios": [{"nom": "outlook", "fichier": "outlook.json"}]})
        self.assertIn("outlook", output.getvalue())
        self.assertNotIn('"scenarios"', output.getvalue())

    def test_nested_menu_and_full_command_are_accepted(self):
        commands = iter(["enregistrement", "lister", "retour",
                         "outils playwright-chrome lister", "quitter"])
        with patch.object(app, "interactive_input", side_effect=lambda *args: next(commands)), \
                patch.object(app, "list_recipes", return_value={"scenarios": []}) as listing, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(app.interactive_shell(), 0)
        self.assertEqual(listing.call_count, 2)
