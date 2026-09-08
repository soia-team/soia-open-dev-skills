"""Structural guards for the batch-1 skill consolidation, not model evals."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
NEW_NAMES = (
    "soia-dev-enforce-coding-protocol",
    "soia-dev-implement-task",
    "soia-dev-review-code",
)
OLD_NAMES = (
    "soia-dev-coding-protocol",
    "soia-dev-task-execute",
    "soia-dev-fix-loop",
    "soia-dev-review-panel",
)


class Batch1Contracts(unittest.TestCase):
    def test_retired_entries_and_runtime_references_are_gone(self):
        for name in OLD_NAMES:
            self.assertFalse((SKILLS / name / "SKILL.md").exists(), name)
        for path in SKILLS.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".yaml", ".yml", ".json"}:
                if "reports" in path.parts:
                    continue
                content = path.read_text(encoding="utf-8")
                for name in OLD_NAMES:
                    self.assertNotIn(name, content, str(path))

    def test_new_entries_have_no_unconditional_skill_dependencies(self):
        for name in NEW_NAMES:
            content = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            metadata = yaml.safe_load(content.split("---", 2)[1])
            self.assertFalse(metadata.get("dependencies", {}).get("hard"), name)

    def test_github_branches_use_optional_current_entries(self):
        content = (SKILLS / "soia-dev-github-ops" / "SKILL.md").read_text()
        metadata = yaml.safe_load(content.split("---", 2)[1])
        self.assertEqual(
            metadata["dependencies"],
            {"optional": ["soia-dev-review-code", "soia-dev-implement-task"]},
        )

    def test_changed_ui_metadata_points_to_its_actual_entry(self):
        for name in (*NEW_NAMES, "soia-dev-show-task-html"):
            path = SKILLS / name / "agents" / "openai.yaml"
            interface = yaml.safe_load(path.read_text())["interface"]
            self.assertIn("$" + name, interface["default_prompt"])
            self.assertGreaterEqual(len(interface["short_description"]), 25)
            self.assertLessEqual(len(interface["short_description"]), 64)


if __name__ == "__main__":
    unittest.main()
