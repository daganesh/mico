# Automated PR review checklist

Review the diff below against the task ID(s) and PRD/AD section(s) named in
the PR title/description, and against `docs/mico-implementation-design.md`
and `docs/mico-prd-v3.md` / `docs/mico-architecture-decisions.md` in the
checked-out repo. Check, in order:

1. **Requirements coverage** — does the diff actually implement what the
   linked task ID and PRD/AD section call for, not a partial stand-in?
2. **Test coverage** — does every new function, branch, and ABC method have
   a corresponding test? Flag anything new that landed untested.
3. **Coding standards:**
   - Security — no secrets logged or committed; safe subprocess/file-path
     handling; no raw-string SQL (must go through the query-spec object).
   - Simplicity and reuse — no duplicated logic, especially where AD-04's
     "narrow port + one shared concrete layer" design already provides a
     shared implementation.
   - No magic numbers or hardcoded strings — thresholds and defaults belong
     in config/constants, not inline literals.
   - Encapsulation — layer boundaries (`mico/brain`, `mico/logic`,
     `mico/ui`) and ABC boundaries (`MetadataStore`, `AgentProvider`,
     `VerificationProvider`, `Scheduler`, `Validator`) are respected; no
     reaching around an interface.
   - Correct API shape for whichever ABC the task implements, matching its
     contract in the design doc and in AD-04/AD-15/PRD §15.2.

List concrete findings with file/line references where possible, ranked by
severity (critical/high/medium/low). A finding at high or critical severity
means the PR should not merge as-is.

End your response with **exactly one** line, and nothing after it:

```
REVIEW_VERDICT: PASS
```

or

```
REVIEW_VERDICT: FAIL
```

`PASS` only if there are no high/critical findings.
