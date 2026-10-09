import csv
import json
import re
import unittest
from collections import Counter
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
EVALS_PATH = SKILL_ROOT / "evals" / "evals.json"
PLAN_PATH = SKILL_ROOT / "evals" / "evaluation-plan.md"

EXPECTED_CATEGORIES = {
    "benchmark-sota",
    "multitrack-sota",
    "open-world-sota",
}
EXPECTED_MODES = {"live_web", "aminer_optional"}
EXPECTED_WORKFLOW_TIERS = {"quick", "standard", "deep"}
EXPECTED_SCENARIO_LAYERS = {"simple_daily", "complex_daily"}
CORE_CAPABILITIES = [
    "query-formulation",
    "source-coverage",
    "scope-comparability",
    "evidence-verification",
    "leaderboard-construction",
    "sota-identification",
    "coverage-gaps",
]
REQUIRED_CASE_FIELDS = {
    "id",
    "name",
    "category",
    "mode",
    "difficulty",
    "prompt",
    "expected_output",
    "files",
    "expectations",
    "failure_conditions",
    "tags",
    "task_summary_zh",
    "prompt_language",
    "user_role",
    "user_goal",
    "scenario_zh",
    "real_user_scenario",
    "workflow_tier",
    "scenario_layer",
    "behavior_class",
    "requires_live_web",
    "capabilities",
}


class EvalSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        cls.cases = cls.data["evals"]

    def test_suite_has_exactly_20_unique_sequential_cases(self):
        ids = [case["id"] for case in self.cases]
        self.assertEqual(self.data["case_count"], 20)
        self.assertEqual(len(self.cases), 20)
        self.assertEqual(ids, list(range(1, 21)))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(self.data.get("suite_version"), "4.1.0")
        self.assertEqual(self.data.get("evaluation_date"), "2026-09-18")

    def test_outcome_weighted_scoring_contract_is_valid(self):
        scoring = self.data["scoring"]
        self.assertEqual(scoring["rubric_version"], "sota-finder.judge-rubric.v3-outcome-weighted")
        self.assertEqual(scoring["scale"]["values"], [0, 1, 2, 3, 4])
        self.assertEqual(len(scoring["expectation_weights"]), len(CORE_CAPABILITIES))
        self.assertEqual(len(scoring["expectation_roles"]), len(CORE_CAPABILITIES))
        self.assertEqual(
            sum(scoring["expectation_weights"]) + scoring["readability_weight"],
            100,
        )
        self.assertGreater(
            scoring["expectation_weights"][4] + scoring["expectation_weights"][5],
            sum(scoring["expectation_weights"][:2]),
        )
        self.assertEqual(scoring["critical_expectation_indexes"], [3, 5, 6])
        self.assertEqual(scoring["efficiency"]["budgets_seconds"], {
            "quick": 600,
            "standard": 1200,
            "deep": 1800,
        })

    def test_declared_categories_modes_and_must_pass_ids_are_consistent(self):
        categories = Counter(case["category"] for case in self.cases)
        modes = Counter(case["mode"] for case in self.cases)
        case_ids = {case["id"] for case in self.cases}
        tagged_must_pass = {
            case["id"] for case in self.cases if "must-pass" in case["tags"]
        }

        self.assertEqual(set(self.data["categories"]), EXPECTED_CATEGORIES)
        self.assertEqual(set(categories), EXPECTED_CATEGORIES)
        self.assertEqual(
            categories,
            Counter({"benchmark-sota": 10, "multitrack-sota": 5, "open-world-sota": 5}),
        )
        self.assertEqual(set(self.data["modes"]), EXPECTED_MODES)
        self.assertEqual(set(modes), EXPECTED_MODES)
        self.assertEqual(modes, Counter({"live_web": 18, "aminer_optional": 2}))
        self.assertTrue(set(self.data["must_pass_ids"]).issubset(case_ids))
        self.assertEqual(set(self.data["must_pass_ids"]), tagged_must_pass)
        self.assertEqual(self.data["must_pass_ids"], [1, 3, 4, 7, 11, 15, 16, 20])

    def test_every_case_is_a_complete_sota_discovery_task(self):
        allowed_difficulty = {"basic", "intermediate", "adversarial"}
        for case in self.cases:
            with self.subTest(case_id=case["id"]):
                self.assertTrue(REQUIRED_CASE_FIELDS.issubset(case))
                self.assertIn(case["category"], EXPECTED_CATEGORIES)
                self.assertIn(case["mode"], EXPECTED_MODES)
                self.assertIn(case["difficulty"], allowed_difficulty)
                self.assertIn(case["prompt_language"], {"zh", "en"})
                self.assertTrue(case["requires_live_web"])
                self.assertTrue(case["real_user_scenario"])
                self.assertEqual(case["behavior_class"], "normal")
                self.assertRegex(case["task_summary_zh"], r"[\u4e00-\u9fff]")
                self.assertTrue(case["user_role"].strip())
                self.assertTrue(case["user_goal"].strip())
                self.assertTrue(case["scenario_zh"].strip())
                self.assertGreaterEqual(len(case["prompt"].strip()), 40)
                self.assertGreaterEqual(len(case["expected_output"].strip()), 40)
                self.assertEqual(len(case["expectations"]), 7)
                self.assertGreaterEqual(len(case["failure_conditions"]), 3)
                self.assertEqual(len(case["expectations"]), len(set(case["expectations"])))
                self.assertEqual(
                    len(case["failure_conditions"]),
                    len(set(case["failure_conditions"])),
                )
                self.assertEqual(case["capabilities"], CORE_CAPABILITIES)
                self.assertIn("sota-discovery", case["tags"])
                if case["prompt_language"] == "zh":
                    self.assertTrue(case["expectations"][5].startswith("先给出清晰、面向用户的结论"))
                else:
                    self.assertTrue(case["expectations"][5].startswith("Lead with a clear user-facing conclusion"))

    def test_suite_is_chinese_first_and_cost_layered(self):
        tiers = Counter(case["workflow_tier"] for case in self.cases)
        layers = Counter(case["scenario_layer"] for case in self.cases)
        behaviors = Counter(case["behavior_class"] for case in self.cases)
        languages = Counter(case["prompt_language"] for case in self.cases)

        self.assertEqual(languages, Counter({"zh": 16, "en": 4}))
        self.assertEqual(tiers, Counter({"quick": 5, "standard": 10, "deep": 5}))
        self.assertEqual(layers, Counter({"simple_daily": 5, "complex_daily": 15}))
        self.assertEqual(behaviors, Counter({"normal": 20}))
        self.assertEqual(
            {case["workflow_tier"] for case in self.cases},
            EXPECTED_WORKFLOW_TIERS,
        )
        self.assertEqual(
            {case["scenario_layer"] for case in self.cases},
            EXPECTED_SCENARIO_LAYERS,
        )
        self.assertTrue(all(
            case["scenario_layer"] == "simple_daily"
            for case in self.cases
            if case["workflow_tier"] == "quick"
        ))
        self.assertTrue(all(
            case["scenario_layer"] == "complex_daily"
            for case in self.cases
            if case["workflow_tier"] in {"standard", "deep"}
        ))

    def test_suite_targets_sota_discovery_instead_of_operational_edge_cases(self):
        prompts = "\n".join(case["prompt"] for case in self.cases)
        tags = {tag for case in self.cases for tag in case["tags"]}

        self.assertRegex(prompts, r"[\u4e00-\u9fff]")
        self.assertRegex(prompts, r"[A-Za-z]")
        self.assertTrue(all("sota" in case["category"] for case in self.cases))
        self.assertTrue(all("leaderboard-construction" in case["capabilities"] for case in self.cases))
        self.assertTrue(all("sota-identification" in case["capabilities"] for case in self.cases))
        self.assertTrue(
            {
                "official-leaderboard",
                "paper-search",
                "preprint-search",
                "repository-search",
                "aggregator-search",
                "metric-direction",
                "protocol-variants",
                "historical",
                "no-unified-benchmark",
                "coverage-gaps",
            }.issubset(tags)
        )
        excluded_primary_tags = {
            "infrastructure-failure",
            "offline-only",
            "privacy",
            "overwrite",
            "schema-only",
            "artifact-only",
            "negative-routing",
        }
        self.assertTrue(excluded_primary_tags.isdisjoint(tags))

    def test_fixture_usage_is_limited_to_the_historical_update_case(self):
        cases_with_files = [case for case in self.cases if case["files"]]
        self.assertEqual([case["id"] for case in cases_with_files], [15])
        self.assertEqual(
            cases_with_files[0]["files"],
            ["evals/fixtures/prior_leaderboard.csv"],
        )

        for relative in cases_with_files[0]["files"]:
            path = (SKILL_ROOT / relative).resolve()
            self.assertTrue(path.is_relative_to(SKILL_ROOT.resolve()))
            self.assertTrue(path.is_file())
            with path.open(encoding="utf-8", newline="") as handle:
                self.assertTrue(list(csv.DictReader(handle)))

    def test_aminer_is_optional_and_not_the_primary_task(self):
        aminer_cases = [case for case in self.cases if case["mode"] == "aminer_optional"]
        self.assertEqual([case["id"] for case in aminer_cases], [17, 18])
        for case in aminer_cases:
            self.assertIn("aminer-optional", case["tags"])
            self.assertNotIn("AMiner", case["user_goal"])
            self.assertIn("可选", case["prompt"])

    def test_historical_suites_are_preserved(self):
        archives = {
            "evals-v1.1.0.json": ("1.1.0", 42),
            "evals-v2.1.1.json": ("2.1.1", 36),
            "evals-v3.0.0.json": ("3.0.0", 14),
        }
        for filename, (version, count) in archives.items():
            path = SKILL_ROOT / "evals" / filename
            self.assertTrue(path.is_file())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["suite_version"], version)
            self.assertEqual(data["case_count"], count)

    def test_evaluation_plan_documents_execution_and_scoring(self):
        text = PLAN_PATH.read_text(encoding="utf-8")
        for marker in (
            "20 cases",
            "SOTA Discovery",
            "benchmark-sota",
            "multitrack-sota",
            "open-world-sota",
            "quick",
            "standard",
            "deep",
            "Must-pass status",
            "Live-web drift policy",
            "tests/test_eval_suite.py",
            "evals-v3.0.0.json",
        ):
            self.assertIn(marker, text)
        for case in self.cases:
            self.assertIn(f"| {case['id']:02d} |", text)


if __name__ == "__main__":
    unittest.main()
