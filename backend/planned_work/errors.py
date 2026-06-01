"""Planned-work domain errors (Sprint 11B Batch 2)."""


class PlannedWorkError(Exception):
    """Carries a stable machine-readable `code` alongside the message,
    mirroring the shape of `extra_work.state_machine.TransitionError`."""

    def __init__(self, message: str, code: str = "planned_work_error") -> None:
        super().__init__(message)
        self.code = code
