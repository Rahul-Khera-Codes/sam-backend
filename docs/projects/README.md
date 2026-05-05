# Projects

Each folder is a self-contained project with its own planning docs.

## Folder structure per project

```
project-name/
  00-overview.md       High-level theory: what, why, architecture decisions
  01-analysis.md       Code analysis: actual files/lines affected, current state
  02-plan.md           Detailed step-by-step implementation plan
  specs/               Per-step specs: exact code changes, file:line references
    step-01.md
    step-02.md
    ...
```

## Projects

| Project | Status | Overview |
|---|---|---|
| billing-ui-update | 🟡 Planning | New pricing table, 5 tiers, minutes-based, overage section |
| per-agent-billing | 🔵 Backlog | Monthly add-on per agent type (Sales, HR, Marketing, Executive) |
```
