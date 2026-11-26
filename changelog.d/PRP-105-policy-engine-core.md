### Added
- Governance policy engine core (PRP-105), detective only. Policies are versioned documents of
  typed rules from a closed list (no expression language); drafts with an unknown kind or bad
  parameters are refused with `invalid_schema`, and a published version is immutable.
- Seven rule evaluators (`model_allow_list`, `data_sensitivity_access`, `residency`,
  `required_owner`, `required_approval`, `registration_required`, `content_rule`) and a plugin
  extension point (`neurosphere_core.governance.policy.rule_plugins`) for later kinds. A kind
  without an evaluator is reported `evaluator_unavailable` and refused at publish with
  `rule_kind_unavailable`.
- Worker role `policy_eval`: de-duplicated violations with evidence ids and no content, resolved
  only after a complete, untruncated run of the rule. Settings
  `NS_POLICY_EVAL_INTERVAL_SECONDS` (300), `NS_POLICY_EVAL_SUBJECT_BUDGET` (5000) and
  `NS_POLICY_EVAL_TIME_BUDGET_SECONDS` (120).
- Time-boxed policy exceptions through the HITL `policy_exception` review kind; the requester
  can never approve their own request.
- Enforcement bindings (`admin_kind: enforcement_binding`), created at `audit` (or `off`);
  `enforce` is only reachable through an approved `enforcement_mode_change` action.
- `PolicyDecider.decide` for later enforcement points: `deny` only under an `enforce` binding
  with no active exception, never from a failure.
- Routes under `/api/v1/governance/policy` (policies, versions, draft, publish, retire,
  violations, exception requests, exceptions, bindings, status), the permissions
  `govpolicy.read` and `govpolicy.manage`, the optional readiness component
  `governance_policy` and settings `NS_GOVPOLICY_ENABLED`, `NS_GOVPOLICY_BACKEND`,
  `NS_GOVPOLICY_EXCEPTION_MAX_DAYS` and `NS_GOVPOLICY_LOCAL_SEED_FILE` (local only).
- Each published policy is projected to the catalog `Policy` entity.
- Runbook `docs/runbooks/governance-policy.md`.

### Changed
- The viewer, analyst, domain steward, admin and security auditor roles hold `govpolicy.read`;
  domain steward and admin hold `govpolicy.manage`.
- Publish and retire draft a `governance_policy_publish` action intent; it stays advisory ("no
  supported write connector") until the PRP-108 platform-control target exists.
