"""Interpret validation timing for reporting without changing engine events."""
from copy import deepcopy
from typing import Any


VALIDATION_EVENTS = {
    "entry_day_volume": frozenset({"VOLUME_CONFIRMATION_PASS", "VOLUME_CONFIRMATION_FAIL"}),
    "day2_confirmation": frozenset({
        "DAY2_CONFIRMATION_PASS", "DAY2_CONFIRMATION_FAIL", "DAY2_CLOSE_CONFIRMATION_FAIL",
    }),
}


def is_close_validation(name: str, metadata: dict[str, Any], kind: str) -> bool:
    # A scheduled OPEN exit reuses the failed decision's name/reason. Never
    # infer a new decision from its name, current daily volume or exit price.
    # Missing timing is unknown, not permission to invent a CLOSE validation.
    return name in VALIDATION_EVENTS[kind] and metadata.get("phase") == "CLOSE"


def scheduled_validation_cards(audit: dict[str, Any]) -> list[tuple[int, str]]:
    """Locate only cards demonstrably built from scheduled OPEN events."""
    incorrect = []
    for index, row in enumerate(audit.get("timeline", [])):
        for kind, names in VALIDATION_EVENTS.items():
            if row.get("validations", {}).get(kind) is None:
                continue
            matching = [event for event in row.get("events", [])
                        if event.get("source_event", event.get("event")) in names]
            phases = {event.get("metadata", {}).get("phase") for event in matching}
            if "OPEN" in phases and "CLOSE" not in phases:
                incorrect.append((index, kind))
    return incorrect


def repair_scheduled_validation_cards(audit: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[int, str]]]:
    """Rebuild affected validation fields from existing timing, without replay.

    Preserve genuine CLOSE cards verbatim, including their original numbers.
    Preserve all events, executions, thresholds, snapshots and PnL verbatim.
    Historical cards with missing timing are left alone rather than guessed.
    """
    corrected = deepcopy(audit)
    changes = scheduled_validation_cards(audit)
    for index, kind in changes:
        corrected["timeline"][index]["validations"][kind] = None
    return corrected, changes
