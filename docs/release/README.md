# Historical release provenance

Everything under `docs/release/**` is **historical release evidence and planning material**, not current Request Engine architecture or release authority.

These documents preserve what a prior V3 release process proved, froze, inventoried, or planned. They may contain:

- exact historical commit/release assumptions;
- obsolete Phase6/G01-G20 gate names;
- paths to release scripts that no longer exist on current HEAD;
- candidate/freeze language that does not constrain the current pre-production optimization phase;
- historical inventories whose current guarantees are now owned elsewhere.

Do not execute commands from these documents as current runbooks without independently verifying the current repository.

For current work start from:

1. `docs/README.md` for document authority and precedence;
2. `docs/architecture/system-optimization-mode.md` for current structural-evolution policy;
3. the current guarantee inventory and owning capability contracts for properties that must remain true;
4. `scripts/ci/run_current_product.sh` and the active CI workflow for current executable proof.

Historical material remains valuable for provenance and archaeology. It must not be used to reintroduce a frozen V3 repository shape into current CI, migrations, architecture tests, or agent instructions.
