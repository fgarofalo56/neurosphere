{{- define "neurosphere.image" -}}
{{- $root := index . 0 -}}
{{- $c := index . 1 -}}
{{- printf "%s/%s:%s" (required "image.registry is required" $root.Values.image.registry) $c.repository (required "image.tag is required" $root.Values.image.tag) -}}
{{- end -}}

{{- define "neurosphere.labels" -}}
app.kubernetes.io/name: neurosphere
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "neurosphere.serviceAccountName" -}}
{{- printf "%s-sa" .Release.Name -}}
{{- end -}}
