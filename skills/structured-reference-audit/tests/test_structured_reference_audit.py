import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "structured_reference_audit.py"
SPEC = importlib.util.spec_from_file_location("structured_reference_audit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class LedgerTest(unittest.TestCase):
    def test_keeps_parse_failure_separate_from_existence(self):
        tei = """<TEI><text><back><listBibl>
        <biblStruct xml:id="b1"><analytic><title type="main">A Reliable Paper</title></analytic><note type="raw_reference">A. Author. A Reliable Paper. 2024.</note></biblStruct>
        <biblStruct xml:id="b2"><analytic><title type="main">Another Reliable Paper</title></analytic><note type="raw_reference">B. Author. Another Reliable Paper. 2024.</note></biblStruct>
        <biblStruct xml:id="b3"><analytic><title type="main">Third Reliable Paper</title></analytic><note type="raw_reference">C. Author. Third Reliable Paper. 2024.</note></biblStruct>
        <biblStruct xml:id="b4"><analytic><title type="main">Fourth Reliable Paper</title></analytic><note type="raw_reference">D. Author. Fourth Reliable Paper. 2024.</note></biblStruct>
        <biblStruct xml:id="b5"><analytic><title type="main">Fifth Reliable Paper</title></analytic><note type="raw_reference">E. Author. Fifth Reliable Paper. 2024.</note></biblStruct>
        <biblStruct xml:id="b6"><analytic><title type="main">Sixth Reliable Paper</title></analytic><note type="raw_reference">F. Author. Sixth Reliable Paper. 2024.</note></biblStruct>
        <biblStruct xml:id="b7"><note type="raw_reference">PMLR</note></biblStruct>
        </listBibl></back></text></TEI>"""
        ledger = MODULE.build_ledger(tei)
        self.assertEqual(ledger["status"], "ready_for_resolution")
        self.assertEqual(ledger["records"][0]["candidate_title"], "A Reliable Paper")
        self.assertFalse(ledger["records"][6]["resolution_eligible"])
        self.assertNotIn("FAKE", str(ledger))

    def test_stops_when_bibliography_is_missing(self):
        ledger = MODULE.build_ledger("<TEI><text><body><p>No references here.</p></body></text></TEI>")
        self.assertEqual(ledger["status"], "references_not_found")
        self.assertEqual(ledger["records"], [])

    def test_aminer_resolution_uses_conservative_statuses(self):
        ledger = {
            "records": [
                {"resolution_eligible": True, "candidate_title": "Attention Is All You Need"},
                {"resolution_eligible": False, "candidate_title": None},
            ]
        }

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"id": "P1", "title": "Attention Is All You Need", "year": 2017}]}

        with patch.object(MODULE.requests, "get", return_value=Response()):
            MODULE.resolve_records(ledger, "test-token", 1)

        self.assertEqual(ledger["records"][0]["status"], "verified_exists")
        self.assertEqual(ledger["records"][1]["status"], "needs_human_review")
        self.assertNotIn("FAKE", str(ledger))

    def test_aminer_requests_include_skill_identity_headers(self):
        ledger = {"records": [{"resolution_eligible": True, "candidate_title": "Attention Is All You Need"}]}

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": []}

        with patch.dict(MODULE.os.environ, {"AMINER_SKILL_RUNTIME": "codex"}, clear=False):
            with patch.object(MODULE.requests, "get", return_value=Response()) as request:
                MODULE.resolve_records(ledger, "test-token", 1)

        headers = request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "test-token")
        self.assertEqual(headers["X-Platform"], "codex")
        self.assertEqual(headers["X-Skill-Name"], "structured-reference-audit")
        self.assertEqual(headers["X-Skill-Version"], "0.1.0")


if __name__ == "__main__":
    unittest.main()
