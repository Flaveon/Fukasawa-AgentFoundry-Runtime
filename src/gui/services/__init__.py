# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""GUI service layer — the only seam between the desktop and the runtime.

Every decision the desktop makes lives behind one of these functions. Views
render what they return and decide nothing; that rule is what makes the desktop
testable without a display and keeps a second validator from growing in the UI
(ADR-007 §1, risk R3).

This is a package rather than a module because the lifecycle work took it past
the ~500-line threshold ADR-007's consequence note names. **The import surface
is deliberately unchanged** — `from src.gui.services import X` works exactly as
it did when this was one file, so no view needed editing for the split.

* `brief` — validate a workflow brief, build its agent packages (the original two)
* `workflow` — the capture → export lifecycle
* `step_editor` — per-field step editing, with guidance read from the rules
* `nodes` — which computers may run agent steps, and how they were found

Nothing here imports customtkinter, tkinter, or prints. If it ever does, the
import-law test in `tests/test_gui_workflow.py` fails.
"""

from src.gui.services.brief import (
    BriefValidation,
    BuildOutcome,
    BuildRefusedError,
    PackageResult,
    build_workflow,
    validate_brief_file,
)
from src.gui.services.nodes import (
    EDITABLE,
    KIND_CHOICES,
    MAY_I_CONTACT,
    NOT_BUILT,
    NOT_CONTACTED,
    REFUSAL_STAGES,
    SCAN_CHOICES,
    UNUSABLE_FILE,
    AddResult,
    FieldView,
    NodeListResult,
    NodeRowView,
    ScanEventView,
    ScanScope,
    add_node,
    check_node,
    forget_node,
    list_nodes,
    save_consent,
    scan,
    typed_in_opening,
    update_field,
)
from src.gui.services.step_editor import (
    CHARACTERISTIC_FIELDS,
    SEPARATOR,
    FieldGuidance,
    StepResult,
    StepView,
    read_step,
    step_field_guidance,
    write_step,
)
from src.gui.services.workflow import (
    EXECUTOR_CLASSES,
    STAGES,
    AgentView,
    AssessmentResult,
    AssessmentView,
    AssignmentView,
    CooperativeResult,
    ExportResult,
    FindingView,
    LifecycleResult,
    ListResult,
    Outcome,
    PromotionResult,
    StageView,
    ValidationResult,
    WorkflowListing,
    accept_finding,
    assess_cooperation,
    build_cooperative,
    create_draft,
    export_brief,
    import_draft,
    lifecycle_status,
    list_workflows,
    override_executor,
    promote_draft,
    reload_draft,
    validate_draft,
)

__all__ = [
    # brief services
    "BriefValidation",
    "BuildOutcome",
    "BuildRefusedError",
    "PackageResult",
    "build_workflow",
    "validate_brief_file",
    # lifecycle results
    "EXECUTOR_CLASSES",
    "STAGES",
    "AgentView",
    "AssessmentResult",
    "AssessmentView",
    "AssignmentView",
    "CooperativeResult",
    "ExportResult",
    "FindingView",
    "LifecycleResult",
    "ListResult",
    "Outcome",
    "PromotionResult",
    "StageView",
    "ValidationResult",
    "WorkflowListing",
    # step editor
    "CHARACTERISTIC_FIELDS",
    "SEPARATOR",
    "FieldGuidance",
    "StepResult",
    "StepView",
    "read_step",
    "step_field_guidance",
    "write_step",
    # lifecycle services
    "accept_finding",
    "assess_cooperation",
    "build_cooperative",
    "create_draft",
    "export_brief",
    "import_draft",
    "lifecycle_status",
    "list_workflows",
    "override_executor",
    "promote_draft",
    "reload_draft",
    "validate_draft",
    # node management
    "EDITABLE",
    "KIND_CHOICES",
    "MAY_I_CONTACT",
    "NOT_BUILT",
    "NOT_CONTACTED",
    "REFUSAL_STAGES",
    "SCAN_CHOICES",
    "UNUSABLE_FILE",
    "AddResult",
    "FieldView",
    "NodeListResult",
    "NodeRowView",
    "ScanEventView",
    # The reach a look is asked for. Re-exported so a view can name the four
    # choices without importing the schema, which ADR-007 §2 forbids.
    "ScanScope",
    "add_node",
    "check_node",
    "forget_node",
    "list_nodes",
    "save_consent",
    "scan",
    "typed_in_opening",
    "update_field",
]
