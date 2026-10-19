# Release Definition-of-Done checklist

Copy this file to `docs/evidence/release/<version>/dod-checklist.md` when cutting a
release, tick the lines, and file the per-release evidence next to it. The
authority for the clauses below is the master index
[Definition of programme done](../../PRPs/PRP-MASTER-neurosphere.md#definition-of-programme-done).

Rules for every line:

- A markdown link points at evidence that already exists under the evidence directory.
- A code-span path containing `<version>` names evidence filed at release time under
  `docs/evidence/release/<version>/`. Replace `<version>` with the release version.
- `OPEN (Gxx)` means the evidence cannot exist yet. The gate id is from the register in
  docs/RESEARCH-AND-GATES.md. A release may ship with OPEN
  lines only if the release notes name them.

Disclaimer: this checklist does not represent FedRAMP authorization, an ATO or
compliance parity. Availability, feature GA and authorization are separate facts, and
none of them is asserted here.

## Programme definition of done

- [ ] Every in-scope PRP is in `PRPs/shipped/` with a completion note: `docs/evidence/release/<version>/prp-status.txt` (output of the PRP index check).
- [ ] Every NS requirement has executable acceptance evidence: `docs/evidence/release/<version>/acceptance-run.txt`.
- [ ] No open critical or high security defect: [supply-chain scan evidence](../evidence/prp-12-supply-chain/local-scan-evidence.md) and `docs/evidence/release/<version>/security-scan.txt`.
- [ ] Profile availability and compliance reviewed, G01 status stated: [G01 evidence](../evidence/G01/README.md). Government analytics and authorized integration tests are OPEN (G01).
- [ ] Profile compliance reviewed, G02 status stated: FedRAMP/DoD boundary and agency ATO are owned by the customer security owner. OPEN (G02).
- [ ] Migrations and rollback tested on the emulator: [migrations emulator run](../evidence/PRP-13/migrations-emulator.md).
- [ ] Migrations and rollback tested against a live account: OPEN (G12), emulator-vs-live deltas are not yet measured.
- [ ] Known limitations documented: `docs/evidence/release/<version>/known-limitations.md`.
- [ ] Production credentials and approvals present only through approved channels: `docs/evidence/release/<version>/credential-channels.md`.
- [ ] Docs, deck and media artefacts verified as real files: OPEN (G09).
- [ ] No FedRAMP authorization, ATO or parity claim anywhere: `docs/evidence/release/<version>/claims-scan.txt`.

## Gate-backed items that bound this release

- [ ] Graph benchmark: [G03 live run](../evidence/G03/live-2026-10-17.md). In-region latency and 429 behaviour remain OPEN (G03).
- [ ] Provider, API and license coverage: OPEN (G04), no live connector contract run.
- [ ] Privacy, retention and legal hold: OPEN (G06).
- [ ] Workload sizing, DR, measured RTO and RPO: OPEN (G07).
- [ ] Dependency and licence pins reviewed: `docs/evidence/release/<version>/dependency-review.txt` (G08 is NARROWED, not closed).
- [ ] Emulator parity deltas recorded: OPEN (G12).

## Release artefacts

- [ ] Images built non-root (uid checked) and scanned with no High or Critical findings: [image builds and scans](../evidence/PRP-13/images.md).
- [ ] Release images scanned at the release digest: `docs/evidence/release/<version>/image-scan.txt`.
- [ ] Signed images verified with cosign: `docs/evidence/release/<version>/cosign-verify.txt`.
- [ ] SBOM attached to each image: `docs/evidence/release/<version>/sbom.txt`.
- [ ] Helm chart packaged and linted: `docs/evidence/release/<version>/helm-package.txt`.
- [ ] CHANGELOG section generated for this version: `docs/evidence/release/<version>/changelog-section.md`.
- [ ] Contract and migration versions recorded in the release notes: `docs/evidence/release/<version>/release-notes.md`.
- [ ] Migrations forward and rollback tested on a snapshot: `docs/evidence/release/<version>/migration-snapshot.txt`.
