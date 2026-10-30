# Operations runbook

> **Status: DRAFT.** Not yet validated by an independent new-user test. See [new-user-test.md](new-user-test.md).

Day-two tasks for the local and compose stack. Targets and probes are in [slo.md](../ops/slo.md) (planning targets, not commitments).

## Health

```bash
make dev-ps
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/readyz
```

`/healthz` is 200 while the process is up and checks no dependency. `/readyz` is 200 only when every dependency probe is `ok`, otherwise 503; the body lists each dependency by reason code and never contains secrets.

## Logs

```bash
make dev-logs
```

## Reset to a known state

```bash
make dev-reset
make seed
```

`make seed-reset` drops only the `sandbox-` databases and restarts the Event Hubs emulator, then `make seed` re-seeds. The Event Hubs emulator has no persistence: events are lost on every `make dev-down`.

## Replay telemetry

```bash
make replay
```

Pushes synthetic events, including injected bad events, to the hub (skips if already present).

## Grant a local role

Authority comes from the policy store, not from app roles. Privileged roles are scoped to domains and time-bound.

```bash
make grant-operator OPERATOR_OID=<object-id> OPERATOR_ROLE=admin
```

## Release verification

Verify signed images, SBOM and the Helm chart: [verify.md](../release/verify.md). Cutting a release needs operator approval: [release-process.md](../release/release-process.md).

## Gate runs

```bash
python scripts/validate_planning.py
make gates
```

Live or paid gates need `NS_LIVE_APPROVED=1` and operator approval; an unrun live gate is reported OPEN.
