# Engineering Quality — Current Roadmap and Definition of Done

> **Lifecycle:** `IMPLEMENTED_FOR_CALIBRATION` / **NOT NORMATIVE**.
>
> Normative promotion remains a separate governance decision.

## 1. Goal

The quality system is successful when optimizing for green normally improves real architecture and maintainability rather than encouraging metric gaming.

The target hierarchy is:

```text
semantic architecture / ownership
    > genuine local reasoning complexity
    > cohesion and locality
    > navigability
    > quantitative metrics
```

## 2. Current operating model

```text
DETERMINISTIC PROOF
    -> accepted architecture/correctness invariants

DETERMINISTIC SIGNALING
    -> reproducible maintainability facts

SEMANTIC REVIEW
    -> contextual interpretation when a heuristic fires

DETERMINISTIC RE-PROOF
    -> verify any applied remediation
```

A semantic reviewer cannot waive a deterministic architecture/correctness `INVARIANT_FAILURE`.

## 3. Current phase summary

| Area | State | Remaining obligation |
|---|---|---|
| Policy direction | `ACCEPTED_FOR_CALIBRATION` | explicit normative promotion later |
| Repository baseline | `IMPLEMENTED_FOR_CALIBRATION` | longitudinal movement and more outlier classification |
| LOC/C901/NAV sensors | `IMPLEMENTED_FOR_CALIBRATION` | measure usefulness/noise and gaming effects |
| Extreme file-size experiment | `HARD RETIRED` | collect evidence before any future blocking proposal |
| Policy/product separation | `REVIEW ONLY` | evaluate causal self-modification, not co-occurrence |
| Evidence packets | `IMPLEMENTED_FOR_CALIBRATION` | simplify if maintenance cost exceeds value |
| Semantic review pilot | `ACTIVE / INCOMPLETE` | genuine human labels and real-PR data |
| Local publish certification | `DX ADJUNCT / CALIBRATION` | measure ergonomics separately from architecture quality |
| Normative promotion | `PENDING` | consolidated authority + explicit precedence update |

## 4. Deterministic architecture proof

The strongest gates remain semantic and repository-specific. Examples include:

- cross-module access through supported contracts;
- approved dependency direction;
- acyclic business-module graph;
- inward domain/application dependencies;
- technical platform ownership;
- composition through supported module surfaces.

These are appropriate HARD gates because the signal is close to the protected property.

Future work should improve traceability and fixture coverage for these invariants rather than invent additional numeric HARD gates.

## 5. Maintainability sensors

### QR-FSIZE-001

```text
effective file LOC > 120
    -> REVIEW_CANDIDATE
```

The threshold asks a question. It does not prescribe a split.

### QR-CPLX-001

```text
Ruff C901 McCabe > 10
    -> REVIEW_CANDIDATE
```

C901 remains outside the global blocking Ruff selection.

### QR-NAV-001

Conservative forwarding/re-export evidence may identify likely navigation/fragmentation cost. It remains contextual and non-blocking.

### Extreme core files

The former rule:

```text
> 500 eLOC scoped core
    -> INVARIANT_FAILURE
```

is retired.

Files above 500 eLOC remain visible through QR-FSIZE. A future dedicated extreme-outlier candidate may be added if it contributes independent signal, but line count alone does not establish architecture invalidity.

## 6. Governance self-modification

The former broad `QR-MEGA-GOV-001` HARD co-occurrence rule is retired.

Current principle:

> A change SHOULD NOT weaken a gate in a way that materially changes a verdict from which the same change benefits.

The current checker surfaces product/policy co-occurrence for review and does not force PR splitting merely because both classes of files changed.

A future HARD implementation would require a precise causal predicate and its own HARD-gate proof.

## 7. Measurement roadmap

Current baseline families include:

- effective file LOC;
- function LOC;
- per-function McCabe;
- nonblank configuration LOC.

Next measurement work should prioritize independent architectural evidence instead of more size metrics. In particular:

- module dependency fan-out/fan-in;
- dependency-edge churn;
- recurring cross-module hotspots;
- navigation/fragmentation trends after metric-triggered remediation.

These should begin as INFORMATIONAL/REVIEW evidence, not thresholds.

## 8. Calibration requirements

Before promoting any heuristic to HARD, collect representative real-change evidence and answer:

1. How often does it fire?
2. How often is healthy code flagged?
3. How often does clearly unhealthy code pass?
4. What is the cheapest literal coding-agent remediation?
5. Does that remediation improve the protected property?
6. Does it create wrappers, micro-files, duplicated logic, or navigation cost?
7. What happens under benign refactors?
8. Is the maintenance/process cost proportional to the protection gained?

Percentiles alone are not sufficient.

## 9. Evidence and semantic review

`quality-scan/v1` and `quality-evidence/v1` remain calibration infrastructure.

They must preserve:

- deterministic fact vs semantic interpretation separation;
- `HEALTHY_AS_IS` and `INSUFFICIENT_CONTEXT` outcomes;
- reviewer/fixer separation;
- deterministic re-proof after remediation;
- inability of an LLM to waive deterministic architecture/correctness failures.

The evidence system should be simplified if it becomes a substantial governance burden without improving decisions.

## 10. Local Publish Certification

Local Publish Certification is deliberately tracked separately from architecture quality.

Its success criteria concern developer workflow/publication integrity:

- exact pushed SHA;
- dirty-tree isolation;
- canonical local proof selection;
- cache correctness;
- no remote-CI bypass.

Its results do not prove cohesion, architecture quality, or the correctness of maintainability thresholds.

## 11. Normative promotion definition of done

The engineering-quality model may become `NORMATIVE` only when all of the following are true:

- Constitution and Fitness Specification are reconciled into one coherent current authority;
- `docs/README.md` explicitly establishes precedence;
- each HARD gate satisfies the complete HARD-gate proof obligation;
- heuristic metrics remain non-blocking unless a newer approved proof justifies otherwise;
- representative longitudinal human calibration exists;
- exception/suppression pressure has been reviewed;
- Goodhart/coding-agent behavior has been observed, not merely theorized;
- governance maintenance cost remains proportional;
- final implementation passes the required GitHub integration proof.

A green calibration PR alone is not normative promotion.

## 12. Acceptance criterion

Before accepting the system as mature, run this adversarial test:

```text
If an agent knows every rule and only wants CI green,
what architecture will the cheapest repairs produce after several years?
```

The expected answer must be closer to:

```text
clear boundaries
cohesive responsibilities
short reasoning paths
low genuine complexity
```

than to:

```text
499-line files
wrapper chains
micro-modules
shared dumping grounds
metric displacement
```
