# Coding Agent Guidelines

Apply these principles throughout this repository. Use judgment for trivial one-step fixes.

## Think Before Coding
- State material assumptions before editing. Ask when ambiguity would waste work.
- Surface tradeoffs and prefer the simpler approach that meets the request.

## Simplicity First
- Write the minimum code needed. Avoid speculative features, abstractions, and configuration.
- Handle realistic failures and preserve validation and security checks.

## Surgical Changes
- Change only what the request requires. Preserve existing style and unrelated behavior.
- Do not refactor working code or delete pre-existing dead code without a request.
- Remove imports, variables, and functions made unused by your own changes.

## Goal-Driven Execution
- Define a checkable outcome, execute, and run relevant checks.
- Report only checks actually performed, including failures and limits.
- Stop when complete or after a serious blocked attempt; do not repeat failing approaches.
