# Automated implementation guidelines

Rules for the Claude Code agent implementing a GitHub issue via the
`claude-implement` label. Read this in full before writing any code.
Determine from the issue's labels and description whether it is a **bug
fix** or a **new feature** and apply that section in addition to the
common rules. If genuinely ambiguous, treat it as a feature (the stricter
of the two).

## Applies to every change

**Do:**
- Stay inside the scope of the linked issue. If the issue is underspecified,
  make the smallest reasonable assumption, state it explicitly in the PR
  description, and proceed -- don't stall.
- Respect the existing layer boundaries (`mico/brain`, `mico/logic`,
  `mico/ui`) and ABC contracts (`MetadataStore`, `AgentProvider`,
  `VerificationProvider`, `Scheduler`, `Validator`) documented in
  `docs/mico-implementation-design.md`. New code implementing one of these
  roles must match its existing contract, not invent a parallel path.
- Write a test for every new function, branch, and ABC method you add.
  Prefer extending existing test files/fixtures over creating new
  parallel ones.
- Keep thresholds, limits, and repeated literals in config/constants, not
  inline magic numbers or strings.
- Run `ruff check .`, `mypy mico`, and `pytest -q --cov=mico
  --cov-report=term-missing` yourself before finishing, and fix anything
  they flag.
- Reference the issue number and, where one exists, the PRD/AD section
  the change implements, in the PR description.

**Don't:**
- Don't touch files outside what the issue requires -- no drive-by
  refactors, renames, or formatting-only changes to unrelated code, even
  if you notice something you'd improve.
- Don't modify anything under `.github/workflows/`, this file, or
  `.github/review-checklist.md`. If the issue seems to require a workflow
  change, stop and leave a comment on the issue explaining why instead of
  editing it.
- Don't add, upgrade, or remove dependencies in `pyproject.toml` unless
  the issue explicitly calls for it.
- Don't log or commit secrets, tokens, or credentials.
- Don't hand-write SQL strings -- go through the existing query-spec
  object.
- Don't weaken or delete an existing test to make the suite pass.
- Don't reach around an ABC/interface boundary to touch a concrete
  implementation directly from another layer.
- Don't leave partially-implemented code paths (e.g. a branch that raises
  `NotImplementedError`) -- either finish it or don't start it, and say so
  in the PR description if you had to cut scope.

## Bug fixes

**Do:**
- First reproduce the bug: write a regression test that fails against the
  current code, then make it pass. Include that test in the diff even if
  it looks redundant with existing tests.
- Fix the root cause. If the true fix is out of scope (e.g. it lives in a
  different layer or requires a design change), say so explicitly in the
  PR description rather than patching a symptom.
- Keep the diff minimal -- a bug fix's footprint should be obviously
  proportional to the bug.

**Don't:**
- Don't refactor the surrounding function/module while you're in there.
  Open a separate issue suggestion in the PR description instead.
- Don't change public function signatures or ABC contracts to fix a bug
  unless the bug *is* an incorrect contract -- if so, call this out
  prominently in the PR description since it's a bigger change than a
  typical fix.

## New features

**Do:**
- Map the implementation explicitly to the PRD/AD section (if any) named
  or implied by the issue; note the section in the PR description per
  AD-04/AD-15/PRD §15.2 conventions already used by the review checklist.
- Design new ABC implementations to satisfy the existing interface first;
  don't introduce a new interface if an existing one already covers the
  need.
- Cover the new code's happy path, edge cases, and error handling with
  tests -- not just the happy path.
- Update `docs/mico-implementation-design.md` (or the relevant doc) if the
  feature changes an ABC contract, adds a new layer boundary, or
  introduces a new module others will need to know about.

**Don't:**
- Don't add a feature flag or config toggle unless the issue asks for
  one -- prefer a clean, direct implementation.
- Don't build speculative extensibility (plugin hooks, generic
  configuration) beyond what the issue asks for.
