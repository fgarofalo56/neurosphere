# Disaster recovery runbook (pointer)

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test.md](new-user-test.md).

This page does not restate disaster recovery. The owning documents are:

- Procedure, targets, measurements and caveats: [dr-runbook.md](../ops/dr-runbook.md). Gate G07 (workload, SLO, DR) stays OPEN; measured values there are from compose and are not representative of production.
- Scripts and safety rules for backup, restore and the drill: [infra/dr/README.md](../../infra/dr/README.md).
- Contingency planning: [contingency-plan.md](../compliance/plans/contingency-plan.md).

Emulator drill (local, synthetic data only):

```bash
make dev-up
uv run python infra/dr/ns_dr.py --help
```

Against a live target the script refuses unless `NS_LIVE_APPROVED=1` and an explicit target are given. A live restore or failover has not been run; it is OPEN until an approved environment exists.
