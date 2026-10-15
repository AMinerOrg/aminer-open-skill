from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_DIR / "scripts" / "paper_set.py"
SPEC = importlib.util.spec_from_file_location("aminer_deep_search_paper_set", MODULE_PATH)
assert SPEC and SPEC.loader
paper_set = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = paper_set
SPEC.loader.exec_module(paper_set)


class PaperSetTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_file = str(Path(self.tmp.name) / "paper_set.json")

    def run_cli(self, argv, stdin_text=None):
        stdout = io.StringIO()
        stdin = io.StringIO(stdin_text or "")
        with contextlib.redirect_stdout(stdout), mock.patch.object(sys, "stdin", stdin):
            code = paper_set.main(["--file", self.state_file, *argv])
        return code, json.loads(stdout.getvalue())

    def add(self, papers, source=None):
        argv = ["add"] + (["--source", source] if source else [])
        return self.run_cli(argv, stdin_text=json.dumps(papers))

    def state(self):
        with open(self.state_file, encoding="utf-8") as file:
            return json.load(file)


class AddTests(PaperSetTestCase):
    def test_add_sets_url_tier_and_source(self):
        code, result = self.add(
            [{"id": "a1", "title": "Graph Neural Networks for Molecules", "year": 2022}],
            source="search:graph neural network",
        )
        self.assertEqual(code, 0)
        self.assertEqual(result, {"added": 1, "duplicates": 0, "merged_versions": 0,
                                  "rejected": 0, "total": 1})
        record = self.state()["papers"]["a1"]
        self.assertEqual(record["url"], "https://www.aminer.cn/pub/a1")
        self.assertEqual(record["tier"], "candidate")
        self.assertEqual(record["found_by"], ["search:graph neural network"])

    def test_same_id_duplicate_merges_fields_and_accumulates_sources(self):
        self.add([{"id": "a1", "title": "Long Enough Paper Title Here"}], source="search:q1")
        code, result = self.add(
            [{"id": "a1", "title": "Long Enough Paper Title Here", "year": 2021, "doi": "10.1/z"}],
            source="search:q2",
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["total"], 1)
        record = self.state()["papers"]["a1"]
        self.assertEqual(record["year"], 2021)  # missing field filled in
        self.assertEqual(record["found_by"], ["search:q1", "search:q2"])

    def test_doi_dedup_across_different_ids(self):
        self.add([{"id": "a1", "title": "Version One Title Alpha", "doi": "10.1/DUP"}])
        code, result = self.add([{"id": "b2", "title": "Different Title Entirely Beta",
                                  "doi": "10.1/dup"}])
        self.assertEqual(code, 0)
        self.assertEqual(result["merged_versions"], 1)
        self.assertEqual(result["total"], 1)
        record = self.state()["papers"]["a1"]
        self.assertEqual(record["alt_ids"], ["b2"])

    def test_normalized_title_dedup_and_published_version_wins(self):
        self.add([{"id": "pre1", "title": "Retrieval-Augmented Generation: A Survey!",
                   "venue": "arXiv (CoRR)", "year": 2023}])
        code, result = self.add([{"id": "pub1",
                                  "title": "Retrieval Augmented Generation  a survey",
                                  "venue": "ACL", "year": 2024, "doi": "10.1/acl"}])
        self.assertEqual(code, 0)
        self.assertEqual(result["merged_versions"], 1)
        record = self.state()["papers"]["pre1"]
        # the published venue/year/doi replace the preprint's
        self.assertEqual(record["venue"], "ACL")
        self.assertEqual(record["year"], 2024)
        self.assertEqual(record["doi"], "10.1/acl")
        self.assertEqual(record["alt_ids"], ["pub1"])

    def test_short_titles_are_not_title_deduped(self):
        self.add([{"id": "a1", "title": "GNN"}])
        code, result = self.add([{"id": "b2", "title": "GNN"}])
        self.assertEqual(code, 0)
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["total"], 2)

    def test_references_items_mark_seeds_expanded_and_record_source(self):
        code, _ = self.add([{"id": "r1", "title": "Cited Paper With A Long Title",
                             "source_paper_ids": ["seed1", "seed2"]}])
        self.assertEqual(code, 0)
        state = self.state()
        self.assertEqual(state["expanded_seeds"], ["seed1", "seed2"])
        self.assertEqual(state["papers"]["r1"]["found_by"],
                         ["references:seed1", "references:seed2"])
        self.assertNotIn("source_paper_ids", state["papers"]["r1"])


class ConstraintTests(PaperSetTestCase):
    def test_init_then_add_enforces_year_range_and_required_fields(self):
        code, result = self.run_cli(["init", "--topic", "graph rag",
                                     "--year-from", "2020", "--year-to", "2024",
                                     "--require-fields", "year,title"])
        self.assertEqual(code, 0)
        self.assertEqual(result["constraints"],
                         {"topic": "graph rag", "year_from": 2020, "year_to": 2024,
                          "require_fields": ["year", "title"]})

        code, result = self.add([
            {"id": "ok", "title": "In Range Paper About Graph RAG", "year": 2021},
            {"id": "old", "title": "Too Old Paper About Graph RAG", "year": 2018},
            {"id": "noyear", "title": "Paper Missing Its Year Field Here"},
        ])
        self.assertEqual(code, 0)
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["rejected"], 2)
        self.assertEqual(result["reject_reasons"],
                         {"year_out_of_range": 1, "missing_year": 1})
        self.assertEqual(set(self.state()["papers"]), {"ok"})

    def test_bare_ids_are_rejected_when_fields_are_required(self):
        self.run_cli(["init", "--require-fields", "year"])
        code, result = self.run_cli(["add", "--ids", "bare1"])
        self.assertEqual(code, 0)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["reject_reasons"], {"missing_year": 1})

    def test_duplicates_of_kept_papers_bypass_constraint_rejection(self):
        self.run_cli(["init", "--year-from", "2020"])
        self.add([{"id": "a1", "title": "A Sufficiently Long Paper Title", "year": 2022}])
        # a bare-id duplicate of an already-kept paper still merges
        code, result = self.run_cli(["add", "--ids", "a1"])
        self.assertEqual(code, 0)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["rejected"], 0)


class TierTests(PaperSetTestCase):
    def test_promote_and_tiered_export(self):
        self.add([
            {"id": "a1", "title": "First Long Paper Title Alpha", "year": 2021},
            {"id": "b2", "title": "Second Long Paper Title Beta", "year": 2022},
        ])
        code, result = self.run_cli(["promote", "--ids", "a1", "ghost"])
        self.assertEqual(code, 0)
        self.assertEqual(result["promoted"], 1)
        self.assertEqual(result["curated_total"], 1)
        self.assertEqual(result["missing_ids"], ["ghost"])

        out_path = str(Path(self.tmp.name) / "curated.json")
        code, result = self.run_cli(["export", "-o", out_path, "--tier", "curated"])
        self.assertEqual(code, 0)
        self.assertEqual(result["count"], 1)
        with open(out_path, encoding="utf-8") as file:
            document = json.load(file)
        self.assertEqual([p["id"] for p in document["papers"]], ["a1"])


class RoundTraceTests(PaperSetTestCase):
    def test_log_round_appends_numbered_records(self):
        self.add([{"id": "a1", "title": "A Sufficiently Long Paper Title", "year": 2021}])
        code, first = self.run_cli(["log-round", "--queries", "graph rag", "kg retrieval",
                                    "--added", "12", "--rejected", "3", "--note", "seed round"])
        self.assertEqual(code, 0)
        self.assertEqual(first["round"], 1)
        self.assertEqual(first["total_after"], 1)
        self.assertEqual(first["queries"], ["graph rag", "kg retrieval"])
        self.assertEqual(first["added"], 12)
        self.assertEqual(first["note"], "seed round")

        code, second = self.run_cli(["log-round", "--added", "5"])
        self.assertEqual(second["round"], 2)
        self.assertEqual(len(self.state()["rounds"]), 2)


class StatsTests(PaperSetTestCase):
    def test_stats_reports_tiers_completeness_and_years(self):
        self.run_cli(["init", "--year-from", "2020"])
        self.add([
            {"id": "a1", "title": "Complete Paper Record Title", "year": 2021,
             "doi": "10.1/a", "abstract_slice": "abs", "authors": ["X"], "venue": "ACL"},
            {"id": "b2", "title": "Sparse Paper Record Title Two", "year": 2022},
        ])
        self.run_cli(["promote", "--ids", "a1"])
        self.run_cli(["log-round", "--added", "2"])
        code, stats = self.run_cli(["stats"])
        self.assertEqual(code, 0)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["tiers"], {"curated": 1, "candidate": 1})
        self.assertEqual(stats["constraints"], {"year_from": 2020})
        self.assertEqual(stats["rounds_logged"], 1)
        self.assertEqual(stats["field_completeness"]["missing_doi"], 1)
        self.assertEqual(stats["field_completeness"]["missing_abstract"], 1)
        self.assertEqual(stats["field_completeness"]["missing_title"], 0)
        self.assertEqual(stats["by_year"], {"2022": 1, "2021": 1})


class ExportTests(PaperSetTestCase):
    def test_export_writes_full_fields_constraints_and_trace(self):
        self.run_cli(["init", "--topic", "graph rag", "--year-from", "2020"])
        self.add([{"id": "a1", "title": "Exported Paper With Full Fields",
                   "year": 2021, "doi": "10.1/a", "venue": "ACL",
                   "authors": ["Alice A"], "n_citation_bucket": "11-50"}],
                 source="search:graph rag")
        self.add([{"id": "notitle"}])  # no title → excluded from export
        self.run_cli(["log-round", "--added", "1"])

        out_path = str(Path(self.tmp.name) / "final.json")
        code, result = self.run_cli(["export", "-o", out_path])
        self.assertEqual(code, 0)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["path"], out_path)
        with open(out_path, encoding="utf-8") as file:
            document = json.load(file)
        self.assertEqual(document["constraints"]["topic"], "graph rag")
        self.assertEqual(len(document["rounds"]), 1)
        self.assertEqual(document["count"], 1)
        paper = document["papers"][0]
        self.assertEqual(paper["id"], "a1")
        self.assertEqual(paper["doi"], "10.1/a")
        self.assertEqual(paper["venue"], "ACL")
        self.assertEqual(paper["authors"], ["Alice A"])
        self.assertEqual(paper["url"], "https://www.aminer.cn/pub/a1")
        self.assertEqual(paper["found_by"], ["search:graph rag"])
        self.assertEqual(paper["tier"], "candidate")

    def test_invalid_stdin_returns_structured_error(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), \
                mock.patch.object(sys, "stdin", io.StringIO("not json")):
            code = paper_set.main(["--file", self.state_file, "add"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["error"], "invalid_input")


class AtomicSaveTests(PaperSetTestCase):
    def test_interrupted_save_leaves_previous_state_intact(self):
        self.add([{"id": "a1", "title": "Survives An Interrupted Save", "year": 2022}])

        def exploding_dump(obj, file, **kwargs):
            file.write('{"papers": {"half')  # partial write, then the crash
            raise OSError("disk full")

        with mock.patch.object(paper_set.json, "dump", exploding_dump), \
                self.assertRaises(OSError):
            self.add([{"id": "b2", "title": "Never Makes It To Disk", "year": 2023}])

        state = self.state()  # must still parse: the real file was never touched
        self.assertEqual(list(state["papers"]), ["a1"])


if __name__ == "__main__":
    unittest.main()
