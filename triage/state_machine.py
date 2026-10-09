# triage/state_machine.py
"""Finding lifecycle state machine.

Manages transitions:
    IDENTIFIED → VALIDATING → CONFIRMED     (real vuln, ready for report)
                            → FALSE_POSITIVE (archived + FP reason saved)
                            → CHAINED       (linked to parent finding)
                            → OUT_OF_SCOPE  (dropped)

Every transition publishes an OrchestrationEvent to the EventBus so the
War Room UI and other components react in real time.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.types import OrchestrationEvent, Task, VulnStatus

logger = logging.getLogger(__name__)

# ── Allowed state transitions ────────────────────────────────────────────
VALID_TRANSITIONS: Dict[VulnStatus, List[VulnStatus]] = {
    VulnStatus.IDENTIFIED: [VulnStatus.VALIDATING, VulnStatus.OUT_OF_SCOPE],
    VulnStatus.VALIDATING: [
        VulnStatus.CONFIRMED,
        VulnStatus.FALSE_POSITIVE,
        VulnStatus.CHAINED,
        VulnStatus.OUT_OF_SCOPE,
    ],
    VulnStatus.CONFIRMED: [VulnStatus.CHAINED],  # can still be linked into a chain
    VulnStatus.FALSE_POSITIVE: [],                # terminal state
    VulnStatus.CHAINED: [],                       # terminal state
    VulnStatus.OUT_OF_SCOPE: [],                  # terminal state
}

# ── Event type emitted per transition target ─────────────────────────────
TRANSITION_EVENTS: Dict[VulnStatus, str] = {
    VulnStatus.VALIDATING:     "validation_started",
    VulnStatus.CONFIRMED:      "finding_confirmed",
    VulnStatus.FALSE_POSITIVE: "false_positive_recorded",
    VulnStatus.CHAINED:        "finding_chained",
    VulnStatus.OUT_OF_SCOPE:   "finding_out_of_scope",
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not permitted."""
    pass


@dataclass
class TransitionRecord:
    """Immutable log of a state change."""
    task_id: str
    from_status: VulnStatus
    to_status: VulnStatus
    evidence: Dict[str, Any] = field(default_factory=dict)
    fp_reason: str = ""


class TriageStateMachine:
    """Manages finding lifecycle and publishes events on transitions.

    Usage:
        sm = TriageStateMachine(event_bus=bus)
        await sm.transition(task, VulnStatus.VALIDATING, evidence={...})
        await sm.transition(task, VulnStatus.CONFIRMED, evidence={"poc": "..."})
    """

    def __init__(self, event_bus=None):
        self._event_bus = event_bus
        self._history: List[TransitionRecord] = []

    async def transition(
        self,
        task: Task,
        new_status: VulnStatus,
        evidence: Optional[Dict[str, Any]] = None,
        fp_reason: str = "",
    ) -> Task:
        """Transition a task to a new status.

        Args:
            task: The task to transition.
            new_status: Target status.
            evidence: Supporting evidence dict (PoC, screenshots, request/response).
            fp_reason: Required when transitioning to FALSE_POSITIVE.

        Returns:
            The updated task.

        Raises:
            InvalidTransitionError: If the transition is not allowed.
        """
        evidence = evidence or {}
        old_status = task.status

        # Validate the transition
        allowed = VALID_TRANSITIONS.get(old_status, [])
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition {task.task_id} from {old_status.value} "
                f"to {new_status.value}. Allowed: {[s.value for s in allowed]}"
            )

        # Require FP reason for FALSE_POSITIVE transitions
        if new_status == VulnStatus.FALSE_POSITIVE and not fp_reason:
            raise InvalidTransitionError(
                f"FP reason required when transitioning {task.task_id} to FALSE_POSITIVE"
            )

        # Apply the transition
        task.status = new_status

        # Log the transition
        record = TransitionRecord(
            task_id=task.task_id,
            from_status=old_status,
            to_status=new_status,
            evidence=evidence,
            fp_reason=fp_reason,
        )
        self._history.append(record)

        logger.info(
            "state_transition",
            extra={
                "task_id": task.task_id,
                "from": old_status.value,
                "to": new_status.value,
                "specialist": task.specialist_id,
                "category": task.vuln_category.value,
                "fp_reason": fp_reason or None,
            },
        )

        # Publish event to bus
        if self._event_bus:
            event_type = TRANSITION_EVENTS.get(new_status, f"status_{new_status.value}")
            event_payload: Dict[str, Any] = {
                "task_id": task.task_id,
                "from_status": old_status.value,
                "to_status": new_status.value,
                "specialist": task.specialist_id,
                "vuln_category": task.vuln_category.value,
                "endpoint": task.target_endpoint,
            }
            if evidence:
                event_payload["evidence_keys"] = list(evidence.keys())
            if fp_reason:
                event_payload["fp_reason"] = fp_reason

            await self._event_bus.publish(
                "triage",
                OrchestrationEvent(
                    event_type=event_type,
                    correlation_id=task.correlation_id,
                    source_component="triage_state_machine",
                    payload=event_payload,
                ),
            )

        return task

    def get_history(self, task_id: Optional[str] = None) -> List[TransitionRecord]:
        """Return transition history, optionally filtered by task_id."""
        if task_id:
            return [r for r in self._history if r.task_id == task_id]
        return self._history.copy()

    def get_status_counts(self) -> Dict[str, int]:
        """Count of findings currently in each status — useful for War Room summary."""
        # This counts the LATEST status per task_id
        latest: Dict[str, VulnStatus] = {}
        for r in self._history:
            latest[r.task_id] = r.to_status
        counts: Dict[str, int] = {}
        for status in latest.values():
            counts[status.value] = counts.get(status.value, 0) + 1
        return counts
