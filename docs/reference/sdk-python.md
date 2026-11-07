# Connector SDK reference (Python)

> Generated file. Do not edit; run `uv run python docs/reference/generate.py`.
> Source commit: `9f478146f48423dcba141896c421bc587829d999`. Generated: 2026-11-07.
> Sources: `connectors/sdk-python/neurosphere_connector/`.

Package `neurosphere_connector` (connector SDK, read side) and `neurosphere_connector.write` (write path, imported explicitly; it is advisory by default and carries no Azure SDK import). Symbols are the `__all__` of each package, extracted from source with `ast`. Public methods are listed under each class.

## `neurosphere_connector`

### `BaseConnector`

```python
class BaseConnector(ABC)
```

Base class: manifest, health, coverage, freshness and credential access.

Methods:

- `def __init__(self, *, credentials: CredentialBroker | None=None, clock: Clock=utc_now) -> None`
- `def manifest(self) -> ConnectorManifest`
- `async def health(self) -> HealthReport`
- `async def coverage(self) -> CoverageReport`
- `async def freshness(self) -> FreshnessReport`
- `async def credential(self, name: str) -> SecretValue`
- `async def guarded_call(self, operation: Callable[[], Awaitable[T]], *, freshness: Callable[[T], FreshnessReport | None] | None=None, coverage: Callable[[T], CoverageReport | None] | None=None) -> T`
- `async def close(self) -> None`

### `CoverageReport`

```python
class CoverageReport(BaseModel)
```

What fraction of expected sources answered. Unknown counts are None.

Methods:

- `def fraction(self) -> float | None`

### `CredentialBroker`

```python
class CredentialBroker
```

Resolves the connector's declared credential refs at call time, with rotation.

Methods:

- `def __init__(self, resolver: CredentialResolver, refs: Iterable[CredentialRef]=()) -> None`
- `def names(self) -> tuple[str, ...]`
- `def on_rotation(self, callback: RotationCallback) -> None`
- `async def get(self, name: str) -> SecretValue`
- `async def notify_rotated(self, name: str | None=None) -> None`
- `async def drain_rotation_hooks(self) -> None`

### `CredentialResolver`

```python
class CredentialResolver(Protocol)
```

Injected by the host; resolves a vault reference (managed identity) to its value.

Methods:

- `async def resolve(self, ref: CredentialRef) -> SecretValue`

### `FreshnessReport`

```python
class FreshnessReport(BaseModel)
```

Observed data lag. ``lag_ms`` is None when unknown (never 0).

### `HealthReport`

```python
class HealthReport(BaseModel)
```

### `HealthState`

```python
class HealthState(StrEnum)
```

### `HealthTracker`

```python
class HealthTracker
```

Accumulates call outcomes and renders a ``HealthReport``.

Methods:

- `def __init__(self, *, clock: Clock=utc_now, failing_after: int=3) -> None`
- `def record_success(self, *, freshness: FreshnessReport | None=None, coverage: CoverageReport | None=None, remaining: int | None=None) -> None`
- `def record_error(self, exc: BaseException) -> None`
- `def snapshot(self) -> HealthReport`

### `RateLimitStatus`

```python
class RateLimitStatus(BaseModel)
```

### `RotationSource`

```python
class RotationSource(Protocol)
```

Optional resolver capability: pushes rotation signals to the broker.

Methods:

- `def subscribe(self, callback: Callable[[str], None]) -> None`

### `SecretValue`

```python
class SecretValue
```

A secret string that cannot leak through repr, str, format, pydantic or json.

Methods:

- `def __init__(self, value: str) -> None`
- `def reveal(self) -> str`

### `StaticCredentialResolver`

```python
class StaticCredentialResolver
```

In-memory resolver for tests and local sandboxes; values keyed by ``vault_ref``.

Methods:

- `def __init__(self, values: Mapping[str, str]) -> None`
- `async def resolve(self, ref: CredentialRef) -> SecretValue`
- `def subscribe(self, callback: Callable[[str], None]) -> None`
- `def rotate(self, ref: CredentialRef, new_value: str) -> None`

### `Violation`

```python
class Violation
```

One contract failure. ``code`` is stable; ``message`` never contains secret values.

### `build_manifest`

```python
def build_manifest(*, name: str, version: str, capabilities: Sequence[Capability], supported_clouds: Sequence[Cloud], granularity: Granularity, freshness: Freshness | None=None, scopes: Sequence[str]=(), rate_limits: Sequence[RateLimit] | None=None, credential_refs: Sequence[CredentialRef]=(), write_actions: Sequence[WriteAction]=(), documentation_url: str | None=None, auth_mode: Literal['managed_identity', 'workload_identity_federation', 'vault_reference'] | None=None, schema_version: str='1.0.0') -> ConnectorManifest
```

Assemble and validate a manifest, deriving ``advisory``, ``write_support`` and auth mode.

### `check_connector_contract`

```python
async def check_connector_contract(connector: Any) -> list[Violation]
```

Check manifest, health, rate-limit, coverage and freshness reporting.

### `manifest_issues`

```python
def manifest_issues(data: Mapping[str, Any] | str | bytes) -> list[ValidationIssue]
```

Return every contract violation (empty list means valid). Messages never hold values.

### `validate_manifest`

```python
def validate_manifest(data: Mapping[str, Any] | str | bytes | ConnectorManifest) -> ConnectorManifest
```

Return the validated manifest or raise ``InvalidSchemaError`` listing the issues.

## `neurosphere_connector.write`

### `AdvisoryWriteMixin`

```python
class AdvisoryWriteMixin
```

Mix into a read-only connector: ``advisory`` is True and writes raise.

Methods:

- `def advisory(self) -> bool`
- `async def dry_run(self, request: WriteRequest) -> DryRunResult`
- `async def apply(self, request: WriteRequest) -> ApplyResult`
- `async def verify(self, request: WriteRequest) -> VerifyResult`
- `async def rollback(self, applied: ApplyResult) -> RollbackResult`

### `ApplyResult`

```python
class ApplyResult(_Model)
```

A real change was made. ``version_after`` is the target's new version/ETag if known.

### `DryRunResult`

```python
class DryRunResult(_Model)
```

Planned change, computed against ``target_version`` of ``target``; nothing was written.

### `OperationCheck`

```python
class OperationCheck(_Model)
```

One requested operation compared with the observed state.

### `RollbackResult`

```python
class RollbackResult(_Model)
```

Outcome of undoing an applied change.

### `VerifyResult`

```python
class VerifyResult(_Model)
```

Observed post-state next to the requested diff, with a computed match.

Methods:

- `def matched(self) -> bool`
- `def mismatched_paths(self) -> tuple[str, ...]`

### `WriteConnector`

```python
class WriteConnector(Protocol)
```

A connector that can really change its target. ``advisory`` must mirror the manifest.

Methods:

- `def manifest(self) -> ConnectorManifest`
- `def advisory(self) -> bool`
- `async def dry_run(self, request: WriteRequest) -> DryRunResult`
- `async def apply(self, request: WriteRequest) -> ApplyResult`
- `async def verify(self, request: WriteRequest) -> VerifyResult`
- `async def rollback(self, applied: ApplyResult) -> RollbackResult`

### `WriteRequest`

```python
class WriteRequest(_Model)
```

What the executor asks a connector to do: exact target, version and diff.

### `WriteTargetRegistry`

```python
class WriteTargetRegistry
```

Connectors accepted as action targets, keyed by manifest name.

Methods:

- `def __init__(self) -> None`
- `def register(self, connector: object) -> WriteConnector`
- `def get(self, name: str) -> WriteConnector`
- `def supports(self, name: str, action: str) -> bool`
- `def names(self) -> tuple[str, ...]`

### `build_verify_result`

```python
def build_verify_result(request: WriteRequest, observed_state: Mapping[str, Any], *, observed_version: str | None=None) -> VerifyResult
```

Helper for implementers: ``observed_state`` must come from reading the real target.

### `check_diff_against_state`

```python
def check_diff_against_state(diff: ProposedDiff, observed_state: Mapping[str, Any]) -> tuple[OperationCheck, ...]
```

Compare each requested operation with the state actually read back from the target.

### `register_write_target`

```python
def register_write_target(registry: WriteTargetRegistry, connector: object) -> WriteConnector
```

Register ``connector`` in ``registry`` or raise ``CapabilityUnavailableError``.

