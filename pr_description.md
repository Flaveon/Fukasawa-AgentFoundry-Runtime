🧪 [Testing improvement for review_gate]

## Description

🎯 **What:** The testing gap addressed
This PR addresses the lack of test coverage for `src/runtime/review_gate.py`. The primary function, `open_review_gate`, requires user interaction through `rich.prompt.Prompt.ask`, which meant it was currently untested. This PR implements unit tests that mock the prompt function, allowing deterministic verification of the review gate behavior.

📊 **Coverage:** What scenarios are now tested
- Validates the return of `ReviewDecision.APPROVE`, `REJECT`, and `FLAG` by mocking human input using parametrized tests.
- Checks correct behavior when a custom `rich.console.Console` is provided, ensuring output functions rely on the passed parameter.
- Covers edge cases when fields such as `evidence` or `evidence_required` are empty strings, guaranteeing stability without exceptions.

✨ **Result:** The improvement in test coverage
The previously untested review logic is now fully verified. The mock-driven tests are completely deterministic and run in milliseconds, solidifying confidence in the gate decision parsing without regressions.
