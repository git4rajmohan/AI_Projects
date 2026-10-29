import io
import json
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class LauncherTest(unittest.TestCase):
    def test_results_scores_logs_and_failure(self):
        answer = "Q: Best stores?\nA: **Top stores**\n\n| Store | Sales |\n|---|---|\n| 2970 | 84454 |\n\nPhoenix UI: http://localhost:6006/\n"
        summary = "__EVAL_UI__" + json.dumps({
            "title": "Overall Experiment", "scores": [
                {"evaluator": "SQL", "passed": 2, "total": 7, "score": 2 / 7},
            ],
        }) + "\n"
        for lab, code in [(0, 0), (3, 0), (3, 1)]:
            with self.subTest(lab=lab, code=code), patch("subprocess.Popen") as popen:
                process = popen.return_value.__enter__.return_value
                process.stdout = io.StringIO(answer + summary)
                process.wait.return_value = code
                app = AppTest.from_file("app.py").run()
                app.selectbox[0].select_index(lab).run()
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertTrue(any("2970" in item.value for item in app.markdown))
                self.assertTrue(any(item.label == "Technical logs" for item in app.expander))
                if lab == 3:
                    self.assertEqual(app.dataframe[-1].value.iloc[0]["Status"], "🟠 Partial")
                    self.assertIn("What it checks", app.dataframe[-1].value.columns)
                    self.assertIn("Where used in agent", app.dataframe[-1].value.columns)
                else:
                    self.assertEqual(len(app.dataframe), 1)
                self.assertEqual(len(app.error), int(code != 0))
                app.run()
                self.assertTrue(any("2970" in item.value for item in app.markdown))
                app.selectbox[0].select_index(1 if lab != 1 else 0).run()
                self.assertFalse(any("2970" in item.value for item in app.markdown))
                self.assertTrue(any("No current output" in item.value for item in app.info))

    def test_selection_guides(self):
        app = AppTest.from_file("app.py").run()
        for lab in range(5):
            app.selectbox[0].select_index(lab).run()
            self.assertFalse(app.exception)
            self.assertTrue(any("What it does" in item.value for item in app.markdown))
            self.assertTrue(any("Expected output / target" in item.value for item in app.markdown))
            reference = app.dataframe[0].value
            self.assertEqual(len(reference), 7)
            self.assertTrue(reference["Where used in agent"].str.contains("generate_sql_query").any())


if __name__ == "__main__":
    unittest.main()
