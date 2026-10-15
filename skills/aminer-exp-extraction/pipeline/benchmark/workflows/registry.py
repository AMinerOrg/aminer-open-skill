"""Workflow registry for benchmark module."""

from __future__ import annotations

from typing import Callable

from pipeline.benchmark.workflows.base import BaseWorkflow

# Type alias for workflow factory
WorkflowFactory = Callable[[], BaseWorkflow]

# Global workflow registry
WORKFLOW_REGISTRY: dict[str, WorkflowFactory] = {}


def register_workflow(workflow_id: str) -> Callable[[type[BaseWorkflow]], type[BaseWorkflow]]:
    """Decorator to register a workflow class in the registry."""
    def decorator(cls: type[BaseWorkflow]) -> type[BaseWorkflow]:
        WORKFLOW_REGISTRY[workflow_id] = cls
        return cls
    return decorator


def get_workflow(workflow_id: str, run_id: str | None = None) -> BaseWorkflow:
    """Get a workflow instance by ID."""
    if workflow_id not in WORKFLOW_REGISTRY:
        raise ValueError(f"Unknown workflow ID: {workflow_id}. Available: {list(WORKFLOW_REGISTRY.keys())}")
    workflow_class = WORKFLOW_REGISTRY[workflow_id]
    return workflow_class(run_id=run_id)


def list_workflows() -> list[str]:
    """List all registered workflow IDs."""
    return list(WORKFLOW_REGISTRY.keys())