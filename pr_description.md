🎯 **What:** The code health issue addressed
Refactored the `promote` function in `src/governance/maturity.py` by extracting logic into helper functions to resolve the "Function is too long" issue.
Extracted logic to `_rewrite_maturity_declarations`, `_fill_mandatory_eval_checks`, and `_record_audit_trail`.

💡 **Why:** How this improves maintainability
Breaking down large functions improves readability and testability. It makes the `promote` function easier to understand and maintain by separating the file rewriting logic, eval checks filling logic, and audit trail recording logic into their respective helper functions.

✅ **Verification:** How you confirmed the change is safe
Ran `python3 -m py_compile src/governance/maturity.py` to check for syntax errors.
Ran the full test suite `python3 -m pytest tests/` which passed successfully, showing no regressions.

✨ **Result:** The improvement achieved
The `promote` function is now much shorter and easier to read. The helper functions are focused on single responsibilities, improving code modularity and maintainability without changing any behavior.
