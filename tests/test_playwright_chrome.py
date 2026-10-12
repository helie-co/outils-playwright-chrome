from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import playwright_chrome as app


class PlaywrightChromeTests(unittest.TestCase):
    def test_parser_accepts_navigation_commands(self):
        arguments = app.parser().parse_args(["ouvrir", "--url", "https://example.com"])
        self.assertEqual(arguments.command, "ouvrir")
        self.assertEqual(arguments.url, "https://example.com")

    def test_recording_defaults_inside_tool(self):
        arguments = app.parser().parse_args(["enregistrer", "--requete", "abc"])
        self.assertIsNone(arguments.fichier)
        self.assertEqual(app.default_recipe_file(arguments.nom), app.ROOT / "scenarios" / "recherche.json")

    def test_write_json_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            app.write_json(target, {"port": 1234})
            self.assertEqual(app.read_state() if target == app.STATE_FILE else {"port": 1234}, {"port": 1234})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"port": 1234})

    def test_status_reports_stopped_when_server_is_unavailable(self):
        with patch.object(app, "request", side_effect=RuntimeError("absent")):
            with patch.object(app, "STATE_FILE") as state_file:
                result = app.main(["etat"])
        self.assertEqual(result, 0)

    def test_recipe_variables_are_replaced(self):
        self.assertEqual(
            app.replace_variables({"url": "https://example.test/{{requete}}"}, {"requete": "abc"}),
            {"url": "https://example.test/abc"},
        )

    def test_recipe_repeats_steps_without_appui(self):
        recipe = {"variables": {"requete": "abc"}, "etapes": [{"action": "attendre", "millisecondes": 1}]}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "recipe.json"
            source.write_text(json.dumps(recipe), encoding="utf-8")
            with patch.object(app, "start"), patch.object(app, "execute_step", return_value={"ok": True}) as execute:
                result = app.execute_recipe(str(source), repetitions=3)
        self.assertEqual(len(result["executions"]), 3)
        self.assertEqual(execute.call_count, 3)

    def test_list_scenarios_reads_json_files(self):
        with tempfile.TemporaryDirectory() as directory:
            scenario = Path(directory) / "scenario.json"
            scenario.write_text(json.dumps({"nom": "scenario", "type": "recherche", "variables": {"q": "x"}}), encoding="utf-8")
            result = app.list_recipes(directory)
        self.assertEqual(result["scenarios"][0]["nom"], "scenario")

    def test_list_recipes_reads_json_scenarios(self):
        with tempfile.TemporaryDirectory() as directory:
            recipe = Path(directory) / "scenario.json"
            recipe.write_text(json.dumps({"nom": "scenario", "type": "recherche", "variables": {"q": "x"}}), encoding="utf-8")
            result = app.list_recipes(directory)
        self.assertEqual(result["scenarios"][0]["nom"], "scenario")


if __name__ == "__main__":
    unittest.main()
