import json
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_required_skill_and_output_contract_are_present(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\nname: sota-finder\n"))
        self.assertNotIn("[TODO", skill)
        for name in ("brief-report.md", "full-report.html", "leaderboards.xlsx", "evidence.json"):
            self.assertIn(name, skill)
        self.assertIn("AMiner is optional", skill)
        self.assertIn("CNY 5", skill)
        self.assertIn("Main Leaderboard", skill)
        self.assertIn("Reference Results", skill)
        self.assertIn("Conflicts / Unavailable", skill)
        self.assertIn("direct / quick / standard / deep", skill)
        self.assertIn("do not load or execute the artifact workflow", skill)
        self.assertIn("Skip this section for `direct`", skill)
        self.assertIn("Results first", skill)
        self.assertIn("reserve time", skill.lower())
        self.assertIn("does not impose a research-call quota", skill)
        self.assertIn("reuse it on the corrected direct result URL", skill)
        self.assertIn("Do not spend the delivery window writing a one-off scraper or parser", skill)
        self.assertIn("enough evidence for the score rows it directly reports", skill)
        self.assertIn("Completeness means useful leaderboard and scope coverage", skill)
        self.assertIn("expected value of another research action", skill)
        self.assertIn("An authoritative result surface is a strong base, not an automatic stop signal", skill)
        self.assertIn("If the host supplies a deadline", skill)
        self.assertIn("Start a working research JSON as soon as", skill)
        self.assertIn("The final builder is the last work step", skill)
        self.assertIn("Requested metadata does not require every row", skill)
        self.assertIn("Do not inspect the full JSON schema", skill)
        self.assertNotIn("stop new source discovery", skill)
        self.assertNotIn("one-way boundary", skill)
        self.assertNotIn("at most one bounded source-reader attempt", skill)
        self.assertIn("Do not inspect the builder source", skill)
        self.assertIn("keep machine keys, stable IDs, enum values", skill)

    def test_user_facing_outputs_are_conclusion_first_and_hide_audit_detail(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        skill_zh = (SKILL_ROOT / "SKILL.zh.md").read_text(encoding="utf-8")
        output_contract = (SKILL_ROOT / "references" / "output-contract.md").read_text(encoding="utf-8")
        data_contract = (SKILL_ROOT / "references" / "data-contract.md").read_text(encoding="utf-8")

        self.assertIn("Lead with the conclusion", skill)
        self.assertIn("首先清楚给出用户真正想获得的结论", skill_zh)
        self.assertIn("Do not include evidence IDs", output_contract)
        self.assertIn("Merge repeated one-row scopes", output_contract)
        self.assertIn("`conclusions`", data_contract)

    def test_prototype_is_self_contained_and_portable(self):
        text_files = [
            path
            for path in SKILL_ROOT.rglob("*")
            if path.is_file()
            and "tests" not in path.relative_to(SKILL_ROOT).parts
            and path.suffix in {".md", ".py", ".json", ".yaml", ".txt"}
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in text_files)
        self.assertNotIn("/Users/", combined)
        self.assertNotIn("leaderboard-builder", combined)
        self.assertNotIn("result-table-extraction", combined)
        self.assertNotIn("AMINER_API_KEY\"]", combined)
        self.assertTrue((SKILL_ROOT / "requirements.txt").exists())
        self.assertEqual((SKILL_ROOT / "requirements.txt").read_text(encoding="utf-8").strip(), "openpyxl>=3.1,<4")

    def test_incremental_tracking_guidance_is_host_agnostic(self):
        core = "\n".join(
            (SKILL_ROOT / relative).read_text(encoding="utf-8")
            for relative in (
                "SKILL.md",
                "SKILL.zh.md",
                "references/data-contract.md",
                "references/research-playbook.md",
            )
        )
        self.assertIn("recurring tracking", core)
        self.assertIn("persistent candidate register", core)
        self.assertIn("Baseline and incremental tracking", core)
        self.assertNotIn("scheduled tracking", core.lower())
        self.assertNotIn("scheduled run", core.lower())

    def test_schema_and_evals_are_machine_readable(self):
        schema = json.loads((SKILL_ROOT / "schemas" / "evidence.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], "urn:aminer-open-skill:sota-finder:evidence:v1")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "sota-finder.evidence.v1")
        self.assertIn("claims", schema["required"])
        self.assertIn("sources", schema["required"])
        self.assertIn("conflicts", schema["required"])

        evals = json.loads((SKILL_ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(evals["skill_name"], "sota-finder")
        self.assertGreaterEqual(len(evals["evals"]), 10)
        self.assertTrue(all(item.get("expectations") for item in evals["evals"]))

    def test_bilingual_and_progressive_disclosure_files_exist(self):
        required = [
            "SKILL.zh.md",
            "commands/sota-finder.md",
            "references/research-playbook.md",
            "references/data-contract.md",
            "references/output-contract.md",
            "scripts/build_outputs.py",
            "scripts/fetch_source.py",
            "tests/fixtures/sample_research.json",
        ]
        for relative in required:
            self.assertTrue((SKILL_ROOT / relative).exists(), relative)

    def test_bilingual_entrypoints_share_the_lean_build_gate(self):
        for relative in ("SKILL.md", "SKILL.zh.md"):
            text = (SKILL_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(file=relative):
                self.assertEqual(text.count("scripts/build_outputs.py"), 2)
                self.assertNotIn('python3 -c "import openpyxl"', text)
                self.assertIn("--validate-only", text)


    def test_multiscope_research_is_breadth_first_without_vague_placeholders(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        skill_zh = (SKILL_ROOT / "SKILL.zh.md").read_text(encoding="utf-8")
        playbook = (SKILL_ROOT / "references" / "research-playbook.md").read_text(encoding="utf-8")
        command = (SKILL_ROOT / "commands" / "sota-finder.md").read_text(encoding="utf-8")

        for phrase in (
            "breadth-first scope inventory",
            "one credible leader or a specific coverage gap",
            "Before deepening any one scope",
            "coverage matrix",
            "unknown` or `unverified",
            "Do not use vague placeholders",
            "Explicitly named scopes are primary",
            "A scope with only one recovered row is usually not a standalone leaderboard",
        ):
            self.assertIn(phrase, skill)

        for phrase in (
            "广度优先的 scope inventory",
            "一个可信榜首或一个具体缺口",
            "深挖任一 scope 前",
            "coverage matrix",
            "`unknown` 或 `unverified`",
            "不要使用模糊占位语",
            "用户明确点名的 scope 属于主范围",
            "只恢复出一行结果的 scope 通常不应单独称为排行榜",
        ):
            self.assertIn(phrase, skill_zh)

        self.assertIn("Breadth-first pass", playbook)
        self.assertIn("coverage matrix", playbook)
        self.assertIn("Merge scopes that share the same comparison protocol", playbook)
        self.assertIn("breadth-first", command)



if __name__ == "__main__":
    unittest.main()
