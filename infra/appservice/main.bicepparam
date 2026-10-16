using './main.bicep'

// Image values MUST equal infra/helm/values.yaml (repositories) and infra/helm/ci/values-ci.yaml
// (placeholder registry/tag); the unit test compares the resolved strings.
param namePrefix = 'neurosphere'
param imageRegistry = 'registry.example.invalid'
param imageTag = '0.1.0'
param apiRepository = 'neurosphere/api'
param workersRepository = 'neurosphere/workers'
