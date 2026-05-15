from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _drafter import validate_draft_output  # noqa: E402


def packet_with_media() -> dict:
    chunks = [
        {
            "chunk_id": "c1",
            "section_path": "Abstract",
            "chunk_text": "The paper introduces a durable method for retaining useful behavior during adaptation.",
            "char_start": 0,
            "char_end": 90,
            "page_num": 1,
        },
        {
            "chunk_id": "c2",
            "section_path": "Method",
            "chunk_text": "The method combines a policy update loop with a reference objective and task feedback.",
            "char_start": 91,
            "char_end": 180,
            "page_num": 2,
        },
        {
            "chunk_id": "c3",
            "section_path": "Method",
            "chunk_text": "The objective balances new task rewards against retention constraints for earlier capabilities.",
            "char_start": 181,
            "char_end": 270,
            "page_num": 3,
        },
        {
            "chunk_id": "c4",
            "section_path": "Results",
            "chunk_text": "The evaluation compares adaptation settings and reports retention differences across benchmarks.",
            "char_start": 271,
            "char_end": 360,
            "page_num": 4,
        },
        {
            "chunk_id": "c5",
            "section_path": "Analysis",
            "chunk_text": "The analysis explains which training choices preserve prior behavior under distribution shift.",
            "char_start": 361,
            "char_end": 450,
            "page_num": 5,
        },
    ]
    return {
        "source_id": "src_test",
        "title": "Retaining Test",
        "source_kind": "local_pdf",
        "source_type": "paper",
        "authors_or_creator": None,
        "published_at": None,
        "canonical_locator": None,
        "extraction_quality": "high",
        "extraction_notes": [],
        "paper_metadata": {},
        "full_paper_text": " ".join(chunk["chunk_text"] for chunk in chunks),
        "drafting_rules": [],
        "draft_template": "",
        "candidate_groups": {},
        "section_blocks": {},
        "chunks": chunks,
        "figures": [{"figure_id": "fig-1", "label": "Figure 1"}],
        "equations": [{"math_id": "eq-1", "label": "Equation 1"}],
    }


def valid_draft() -> dict:
    return {
        "media_review": {
            "figures_reviewed": True,
            "equations_reviewed": True,
            "no_media_reason": "",
        },
        "big_picture": {
            "text": "The paper studies how adaptation can retain useful prior behavior while learning new task behavior.",
            "chunk_ids": ["c1"],
        },
        "problem_setting": {
            "text": "The setting concerns models that must adapt without losing capabilities that remain useful later.",
            "chunk_ids": ["c1"],
        },
        "core_claims": [
            {
                "title": "Retention needs explicit pressure",
                "text": "The main claim is that adaptation should preserve earlier capabilities while optimizing the new task.",
                "chunk_ids": ["c1", "c2"],
            }
        ],
        "method_overview": {
            "text": "The method uses a top level adaptation loop that combines task feedback with a reference objective so the updated policy changes where needed while retaining earlier behavior.",
            "chunk_ids": ["c2"],
            "figure_ids": ["fig-1"],
        },
        "method_details": [
            {
                "title": "Retention objective",
                "text": "The objective balances new task rewards with constraints that discourage unnecessary drift from prior behavior.",
                "chunk_ids": ["c3"],
                "equation_ids": ["eq-1"],
            }
        ],
        "data_or_inputs": [],
        "experimental_setup": [],
        "results": [
            {
                "title": "Retention comparison",
                "text": "The evaluation compares adaptation settings and reports retention differences across benchmark conditions.",
                "chunk_ids": ["c4"],
            }
        ],
        "analysis": [
            {
                "title": "Training choice sensitivity",
                "text": "The analysis explains which training choices most affect preserving prior behavior after adaptation.",
                "chunk_ids": ["c5"],
            }
        ],
        "limitations": [],
        "open_questions": [],
    }


class DraftMediaReviewTest(unittest.TestCase):
    def test_available_media_with_selected_valid_ids_passes(self) -> None:
        normalized = validate_draft_output(packet_with_media(), valid_draft(), strict=True)

        self.assertEqual(normalized["method_overview"]["figure_ids"], ["fig-1"])
        self.assertEqual(normalized["method_details"][0]["equation_ids"], ["eq-1"])

    def test_available_media_with_no_selected_ids_fails(self) -> None:
        draft = valid_draft()
        draft["method_overview"].pop("figure_ids")
        draft["method_details"][0].pop("equation_ids")

        with self.assertRaisesRegex(ValueError, "selected no media"):
            validate_draft_output(packet_with_media(), draft, strict=True)

    def test_available_media_with_no_selected_ids_and_reason_passes(self) -> None:
        draft = valid_draft()
        draft["method_overview"].pop("figure_ids")
        draft["method_details"][0].pop("equation_ids")
        draft["media_review"]["no_media_reason"] = (
            "The extracted media are duplicated fragments and do not clarify the note."
        )

        normalized = validate_draft_output(packet_with_media(), draft, strict=True)

        self.assertEqual(normalized["media_review"]["no_media_reason"], draft["media_review"]["no_media_reason"])

    def test_unknown_figure_or_equation_ids_fail(self) -> None:
        draft = valid_draft()
        draft["method_overview"]["figure_ids"] = ["missing-figure"]

        with self.assertRaisesRegex(ValueError, "unknown figure ids"):
            validate_draft_output(packet_with_media(), draft, strict=True)

        draft = valid_draft()
        draft["method_details"][0]["equation_ids"] = ["missing-equation"]

        with self.assertRaisesRegex(ValueError, "unknown equation ids"):
            validate_draft_output(packet_with_media(), draft, strict=True)

    def test_equation_labels_are_not_valid_equation_ids(self) -> None:
        draft = valid_draft()
        draft["method_details"][0]["equation_ids"] = ["Equation 1"]

        with self.assertRaisesRegex(ValueError, "unknown equation ids"):
            validate_draft_output(packet_with_media(), draft, strict=True)

    def test_selected_equation_with_notation_explanation_passes(self) -> None:
        draft = valid_draft()
        draft["method_details"][0]["text"] = (
            "The retention objective combines task reward with a drift penalty, "
            "where the penalty denotes the constraint that keeps the adapted policy "
            "near earlier behavior."
        )

        normalized = validate_draft_output(packet_with_media(), draft, strict=True)

        self.assertEqual(normalized["method_details"][0]["equation_ids"], ["eq-1"])

    def test_selected_equation_without_notation_explanation_fails(self) -> None:
        draft = valid_draft()
        draft["method_details"][0]["text"] = (
            "The method uses $L = R - D$ for adaptation and applies it during updates."
        )

        with self.assertRaisesRegex(ValueError, "does not explain the notation"):
            validate_draft_output(packet_with_media(), draft, strict=True)

    def test_selected_conceptual_figure_in_method_overview_passes(self) -> None:
        draft = valid_draft()
        draft["method_overview"]["figure_ids"] = ["fig-1"]

        normalized = validate_draft_output(packet_with_media(), draft, strict=True)

        self.assertEqual(normalized["method_overview"]["figure_ids"], ["fig-1"])

    def test_reusing_one_chunk_in_four_sections_fails(self) -> None:
        draft = valid_draft()
        draft["problem_setting"]["chunk_ids"] = ["c2"]
        draft["core_claims"][0]["chunk_ids"] = ["c2"]
        draft["method_details"][0]["chunk_ids"] = ["c2"]

        with self.assertRaisesRegex(ValueError, "reused too broadly"):
            validate_draft_output(packet_with_media(), draft, strict=True)

    def test_section_list_type_mismatch_fails(self) -> None:
        draft = valid_draft()
        draft["results"] = {
            "title": "Wrong shape",
            "text": "This should be a list of result objects.",
            "chunk_ids": ["c4"],
        }

        with self.assertRaisesRegex(ValueError, "draft section list must be a list"):
            validate_draft_output(packet_with_media(), draft, strict=True)

    def test_method_overview_without_overview_cues_fails(self) -> None:
        draft = valid_draft()
        draft["method_overview"]["text"] = (
            "The implementation uses batch size, learning rate, optimizer settings, "
            "epochs, and hyperparameters for training details."
        )

        with self.assertRaisesRegex(ValueError, "narrow technical details"):
            validate_draft_output(packet_with_media(), draft, strict=True)

    def test_missing_media_review_for_available_media_fails(self) -> None:
        draft = valid_draft()
        draft.pop("media_review")

        with self.assertRaisesRegex(ValueError, "must include media_review"):
            validate_draft_output(packet_with_media(), draft, strict=True)

    def test_media_objects_without_ids_still_require_review(self) -> None:
        packet = copy.deepcopy(packet_with_media())
        packet["figures"] = [{"caption": "Extracted framework figure"}]
        packet["equations"] = []
        draft = valid_draft()
        draft["method_overview"].pop("figure_ids")
        draft["method_details"][0].pop("equation_ids")

        with self.assertRaisesRegex(ValueError, "selected no media"):
            validate_draft_output(packet, draft, strict=True)

        draft["media_review"]["no_media_reason"] = "The extracted figure has no usable stable ID."
        normalized = validate_draft_output(packet, draft, strict=True)
        self.assertEqual(
            normalized["media_review"]["no_media_reason"],
            "The extracted figure has no usable stable ID.",
        )

    def test_missing_media_review_for_text_only_packet_passes(self) -> None:
        packet = copy.deepcopy(packet_with_media())
        packet["figures"] = []
        packet["equations"] = []
        draft = valid_draft()
        draft.pop("media_review")
        draft["method_overview"].pop("figure_ids")
        draft["method_details"][0].pop("equation_ids")

        normalized = validate_draft_output(packet, draft, strict=True)

        self.assertEqual(normalized["media_review"]["no_media_reason"], "")


if __name__ == "__main__":
    unittest.main()
