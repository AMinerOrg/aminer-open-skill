"""Strategy-agnostic text preprocessing for experiment extraction."""

from .compact_markdown import CompactMarkdownResult, compact_markdown
from .pipeline import run_preprocess_steps
from .section_union import SectionUnionResult, union_experiment_sections
from .section_union_abs_intro import SectionUnionAbsIntroResult, union_abs_intro_sections
from .strip_references import StripReferencesResult, strip_references

__all__ = [
    "CompactMarkdownResult",
    "SectionUnionAbsIntroResult",
    "SectionUnionResult",
    "StripReferencesResult",
    "compact_markdown",
    "run_preprocess_steps",
    "strip_references",
    "union_abs_intro_sections",
    "union_experiment_sections",
]
