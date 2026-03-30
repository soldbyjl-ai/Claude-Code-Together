# Claude Code Together — Project Constitution

> This is the **single source of truth** for the project's data schemas, behavioral rules, and architectural invariants.
> Any schema change, rule addition, or architecture modification **must** be reflected here.

---

## Data Schemas

> _To be defined after Discovery Questions are answered._

### Input Schema
```json
{}
```

### Output Schema
```json
{}
```

---

## Behavioral Rules

> _To be defined after Discovery Questions are answered._

1. _Pending_

---

## Architectural Invariants

1. **3-Layer Separation:** Architecture SOPs (`architecture/`) → Navigation (decision routing) → Tools (`tools/`)
2. **Data-First:** No tool is built until its input/output schema is defined in this file
3. **Self-Annealing:** Every error results in a fix, a test, and an architecture SOP update
4. **Deterministic Tools:** Business logic in `tools/` must be deterministic Python — no LLM calls inside tool scripts
5. **Intermediates are ephemeral:** `.tmp/` contents are disposable; only the final payload matters
