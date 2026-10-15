"""板块 6 · 全字段生产线 (production orchestration layer).

Only ``pipeline/production/**`` is allowed to be modified here. This layer is a
consumer of the frozen 板块 5 benchmark (wf8) and the remote
``rule_ml_extraction_from_promote/rule_extraction_pack`` rule/ML pack — it never
mutates them.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
