"""Base workflow abstract class for benchmark workflows."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.benchmark.config import RUNS_DIR


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkflowInput:
    """Input data for a workflow run."""
    paper_id: str
    md_path: Path
    run_id: str


@dataclass
class WorkflowResult:
    """Result from running a workflow."""
    workflow_id: str
    workflow_version: str
    run_id: str
    paper_id: str
    prediction: dict[str, Any]
    monitor: dict[str, Any] = field(default_factory=dict)
    paper_title: str = ""
    error: str | None = None


class BaseWorkflow(ABC):
    """Abstract base class for benchmark workflows."""

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id or f"bench-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    @property
    @abstractmethod
    def workflow_id(self) -> str:
        """Unique identifier for this workflow."""
        ...

    @property
    @abstractmethod
    def workflow_version(self) -> str:
        """Version of this workflow implementation."""
        ...

    @abstractmethod
    def run(self, input_data: WorkflowInput) -> WorkflowResult:
        """Execute the workflow on a single paper."""
        ...

    def get_output_dir(self, workflow_name: str) -> Path:
        """Get output directory for this workflow run."""
        return RUNS_DIR / self.run_id / workflow_name / "predictions"

    def get_monitor_dir(self, workflow_name: str) -> Path:
        """Get monitor directory for this workflow run."""
        return RUNS_DIR / self.run_id / workflow_name / "monitors"

    def save_prediction(
        self,
        workflow_name: str,
        paper_id: str,
        prediction: dict[str, Any],
        monitor: dict[str, Any] | None = None,
    ) -> tuple[Path, Path]:
        """Save prediction and monitor files to output directory."""
        output_dir = self.get_output_dir(workflow_name)
        monitor_dir = self.get_monitor_dir(workflow_name)

        output_dir.mkdir(parents=True, exist_ok=True)
        monitor_dir.mkdir(parents=True, exist_ok=True)

        pred_path = output_dir / f"{paper_id}.json"
        monitor_path = monitor_dir / f"{paper_id}_monitor.json"

        pred_path.write_text(json.dumps(prediction, indent=2, ensure_ascii=False), encoding="utf-8")

        if monitor:
            monitor_path.write_text(json.dumps(monitor, indent=2, ensure_ascii=False), encoding="utf-8")

        return pred_path, monitor_path