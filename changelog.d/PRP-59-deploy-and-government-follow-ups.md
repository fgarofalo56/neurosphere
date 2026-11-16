### Changed
- PRP-59: `POST /api/v1/deploy/plan` refuses a request-body `scan` (422 `scan_body_not_accepted`); plan from the server-issued `scan_id`. The deploy UI and mock API send `scan_id`.
- PRP-59: the scan consent audit record carries the authenticated principal pseudonym as `consented_by` and a hash of the client attestation.
- PRP-59: `infra/scripts/uninstall.py` knows every top-level ARM type the Bicep tree declares (coverage test added); DoD regions are no longer treated as Government in copilot gating, capabilities and the mock.
- PRP-59: G02 profile teardown writes evidence on interrupt, re-checks resource tags before deleting the group and narrows the AKS cleanup exception; `confine_evidence_dir` is shared in `scripts/gates/_evidence_paths.py`.
