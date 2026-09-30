{{/* ---------------------------------------------------------------------------
Names and labels
--------------------------------------------------------------------------- */}}

{{- define "soundings.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Release-scoped base name; component suffixes are appended to it. */}}
{{- define "soundings.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 50 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 50 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 50 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "soundings.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "soundings.selectorLabels" -}}
app.kubernetes.io/name: {{ include "soundings.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "soundings.labels" -}}
helm.sh/chart: {{ include "soundings.chart" . }}
{{ include "soundings.selectorLabels" . }}
app.kubernetes.io/version: {{ include "soundings.imageTag" . | trunc 63 | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: soundings
{{- end }}

{{/* Usage: include "soundings.componentLabels" (dict "ctx" $ "component" "api") */}}
{{- define "soundings.componentLabels" -}}
{{ include "soundings.labels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "soundings.componentSelectorLabels" -}}
{{ include "soundings.selectorLabels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/* Pod template labels: component labels plus podLabels. */}}
{{- define "soundings.podLabels" -}}
{{ include "soundings.componentLabels" . }}
{{- with .ctx.Values.podLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "soundings.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "soundings.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* ---------------------------------------------------------------------------
Images
--------------------------------------------------------------------------- */}}

{{- define "soundings.imageTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion | toString }}
{{- end }}

{{- define "soundings.image" -}}
{{- $registry := .Values.global.imageRegistry | default .Values.image.registry }}
{{- $ref := printf "%s:%s" .Values.image.repository (include "soundings.imageTag" .) }}
{{- if $registry }}{{ $ref = printf "%s/%s" $registry $ref }}{{ end }}
{{- if .Values.image.digest }}{{ $ref = printf "%s@%s" $ref .Values.image.digest }}{{ end }}
{{- $ref }}
{{- end }}

{{- define "soundings.postgresql.image" -}}
{{- $image := .Values.postgresql.image }}
{{- $registry := .Values.global.imageRegistry | default $image.registry }}
{{- $ref := printf "%s:%s" $image.repository ($image.tag | toString) }}
{{- if $registry }}{{ $ref = printf "%s/%s" $registry $ref }}{{ end }}
{{- $ref }}
{{- end }}

{{- define "soundings.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end }}

{{/* ---------------------------------------------------------------------------
Secrets
--------------------------------------------------------------------------- */}}

{{/*
Base64 value of key `key` in Secret `name` if it already exists (so generated values
survive upgrades), else `length` random alphanumerics. lookup returns nothing under
`helm template` / --dry-run / Argo CD: use the existingSecret values there.
Usage: include "soundings.lookupOrGenerate" (dict "ctx" $ "name" "x" "key" "y" "length" 48)
*/}}
{{- define "soundings.lookupOrGenerate" -}}
{{- $existing := lookup "v1" "Secret" .ctx.Release.Namespace .name }}
{{- $data := dict }}
{{- if $existing }}{{ $data = $existing.data | default dict }}{{ end }}
{{- if hasKey $data .key }}
{{- index $data .key }}
{{- else }}
{{- randAlphaNum (int .length) | b64enc }}
{{- end }}
{{- end }}

{{- define "soundings.secretKey.secretName" -}}
{{- .Values.secretKey.existingSecret | default (include "soundings.fullname" .) }}
{{- end }}

{{- define "soundings.secretKey.key" -}}
{{- if .Values.secretKey.existingSecret }}{{ .Values.secretKey.existingSecretKey }}{{ else }}secret-key{{ end }}
{{- end }}

{{- define "soundings.postgresql.fullname" -}}
{{- printf "%s-postgresql" (include "soundings.fullname" .) }}
{{- end }}

{{- define "soundings.postgresql.secretName" -}}
{{- .Values.postgresql.auth.existingSecret | default (include "soundings.postgresql.fullname" .) }}
{{- end }}

{{- define "soundings.postgresql.secretKey" -}}
{{- if .Values.postgresql.auth.existingSecret }}{{ .Values.postgresql.auth.existingSecretKey }}{{ else }}password{{ end }}
{{- end }}

{{/* Whether the app gets SOUNDINGS_DATABASE_PASSWORD from a Secret at all. */}}
{{- define "soundings.database.hasPassword" -}}
{{- if or .Values.postgresql.enabled .Values.externalDatabase.existingSecret .Values.externalDatabase.password }}true{{ end }}
{{- end }}

{{/* Secret (name, key) with the database password for the api/worker pods. */}}
{{- define "soundings.database.secretName" -}}
{{- if .Values.postgresql.enabled }}
{{- include "soundings.postgresql.secretName" . }}
{{- else if .Values.externalDatabase.existingSecret }}
{{- .Values.externalDatabase.existingSecret }}
{{- else }}
{{- include "soundings.fullname" . }}
{{- end }}
{{- end }}

{{- define "soundings.database.secretKey" -}}
{{- if .Values.postgresql.enabled }}
{{- include "soundings.postgresql.secretKey" . }}
{{- else if .Values.externalDatabase.existingSecret }}
{{- .Values.externalDatabase.existingSecretPasswordKey }}
{{- else }}database-password{{ end }}
{{- end }}

{{/* ---------------------------------------------------------------------------
Configuration
--------------------------------------------------------------------------- */}}

{{- define "soundings.databaseUrl" -}}
{{- if .Values.postgresql.enabled }}
{{- printf "postgresql+psycopg://%s@%s:5432/%s?sslmode=disable" .Values.postgresql.auth.username (include "soundings.postgresql.fullname" .) .Values.postgresql.auth.database }}
{{- else }}
{{- $db := .Values.externalDatabase }}
{{- printf "postgresql+psycopg://%s@%s:%d/%s?sslmode=%s" ($db.user | urlquery) $db.host (int $db.port) $db.database $db.sslmode }}
{{- end }}
{{- end }}

{{/* Hostnames of baseUrls (YAML list). */}}
{{- define "soundings.baseHosts" -}}
{{- $hosts := list }}
{{- range .Values.baseUrls }}
{{- $hosts = append $hosts ((urlParse .).host | splitList ":" | first) }}
{{- end }}
{{- toYaml ($hosts | uniq) }}
{{- end }}

{{- define "soundings.smtpCaPath" -}}
{{- printf "/etc/soundings/smtp-ca/%s" .Values.smtp.caBundle.key }}
{{- end }}

{{/*
Non-secret SOUNDINGS_* settings as a YAML map (the ConfigMap's data, and inline env
for the pre-install migration Job, which runs before the ConfigMap exists).
*/}}
{{- define "soundings.configEnv" -}}
SOUNDINGS_ENVIRONMENT: {{ ternary "development" "production" .Values.devLogin | quote }}
SOUNDINGS_DEV_LOGIN_ENABLED: {{ .Values.devLogin | quote }}
SOUNDINGS_BASE_URLS: {{ join "," .Values.baseUrls | quote }}
SOUNDINGS_TRUSTED_PROXIES: {{ join "," .Values.trustedProxies | quote }}
SOUNDINGS_LOG_LEVEL: {{ .Values.logLevel | quote }}
SOUNDINGS_DATABASE_URL: {{ include "soundings.databaseUrl" . | quote }}
SOUNDINGS_METRICS_PORT: {{ .Values.metrics.port | quote }}
SOUNDINGS_SESSION_IDLE_TIMEOUT: {{ .Values.sessions.idleTimeout | quote }}
SOUNDINGS_SESSION_MAX_AGE: {{ .Values.sessions.maxAge | quote }}
SOUNDINGS_WORKER_CONCURRENCY: {{ .Values.worker.concurrency | quote }}
SOUNDINGS_FEATURE_PUBLIC_SUBMISSION: {{ .Values.features.publicSubmission | quote }}
SOUNDINGS_FEATURE_AI: {{ .Values.features.ai | quote }}
SOUNDINGS_BREAK_GLASS_ENABLED: {{ .Values.breakGlass.enabled | quote }}
{{- with .Values.otel.endpoint }}
SOUNDINGS_OTEL_ENDPOINT: {{ . | quote }}
{{- end }}
{{- if .Values.oidc.issuer }}
SOUNDINGS_OIDC_ISSUER: {{ .Values.oidc.issuer | quote }}
SOUNDINGS_OIDC_CLIENT_ID: {{ .Values.oidc.clientId | quote }}
SOUNDINGS_OIDC_GROUPS_CLAIM: {{ .Values.oidc.groupsClaim | quote }}
SOUNDINGS_OIDC_SCOPES: {{ join "," .Values.oidc.scopes | quote }}
{{- with .Values.oidc.externalIdClaim }}
SOUNDINGS_OIDC_EXTERNAL_ID_CLAIM: {{ . | quote }}
{{- end }}
{{- end }}
{{- if .Values.smtp.host }}
SOUNDINGS_SMTP_HOST: {{ .Values.smtp.host | quote }}
SOUNDINGS_SMTP_PORT: {{ .Values.smtp.port | quote }}
SOUNDINGS_SMTP_SECURITY: {{ .Values.smtp.security | quote }}
SOUNDINGS_SMTP_FROM: {{ .Values.smtp.from | quote }}
SOUNDINGS_SMTP_FROM_NAME: {{ .Values.smtp.fromName | quote }}
SOUNDINGS_SMTP_TIMEOUT: {{ .Values.smtp.timeout | quote }}
{{- with .Values.smtp.replyTo }}
SOUNDINGS_SMTP_REPLY_TO: {{ . | quote }}
{{- end }}
{{- if .Values.smtp.caBundle.configMap }}
SOUNDINGS_SMTP_CA_BUNDLE: {{ include "soundings.smtpCaPath" . | quote }}
{{- end }}
{{- end }}
{{- end }}

{{/* env entries for the secrets of api/worker pods (the chart's Secrets exist by then). */}}
{{/* env entry for the database password, when there is one (api/worker pods and Jobs). */}}
{{- define "soundings.databasePasswordEnv" -}}
{{- if include "soundings.database.hasPassword" . }}
- name: SOUNDINGS_DATABASE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "soundings.database.secretName" . }}
      key: {{ include "soundings.database.secretKey" . }}
{{- end }}
{{- end }}

{{/*
env for containers that only talk to the database (wait-for-db, migrate, seed): the
password and extraEnv (e.g. PGSSLROOTCERT), none of the app's other secrets.
*/}}
{{- define "soundings.databaseEnv" -}}
{{ include "soundings.databasePasswordEnv" . }}
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "soundings.secretEnv" -}}
{{- $fullname := include "soundings.fullname" . -}}
- name: SOUNDINGS_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "soundings.secretKey.secretName" . }}
      key: {{ include "soundings.secretKey.key" . }}
{{- include "soundings.databasePasswordEnv" . }}
{{- if and .Values.oidc.issuer (or .Values.oidc.existingSecret .Values.oidc.clientSecret) }}
- name: SOUNDINGS_OIDC_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ .Values.oidc.existingSecret | default $fullname }}
      key: {{ ternary .Values.oidc.existingSecretKey "oidc-client-secret" (not (empty .Values.oidc.existingSecret)) }}
{{- end }}
{{- if .Values.smtp.host }}
{{- if .Values.smtp.existingSecret }}
- name: SOUNDINGS_SMTP_USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ .Values.smtp.existingSecret }}
      key: username
      optional: true
- name: SOUNDINGS_SMTP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.smtp.existingSecret }}
      key: password
      optional: true
{{- else }}
{{- if .Values.smtp.username }}
- name: SOUNDINGS_SMTP_USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ $fullname }}
      key: smtp-username
{{- end }}
{{- if .Values.smtp.password }}
- name: SOUNDINGS_SMTP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ $fullname }}
      key: smtp-password
{{- end }}
{{- end }}
{{- end }}
{{- if .Values.breakGlass.enabled }}
- name: SOUNDINGS_BREAK_GLASS_USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ .Values.breakGlass.existingSecret | default $fullname }}
      key: {{ ternary "username" "break-glass-username" (not (empty .Values.breakGlass.existingSecret)) }}
- name: SOUNDINGS_BREAK_GLASS_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.breakGlass.existingSecret | default $fullname }}
      key: {{ ternary "password" "break-glass-password" (not (empty .Values.breakGlass.existingSecret)) }}
{{- end }}
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/* envFrom for api/worker: the chart's ConfigMap plus extraEnvFrom. */}}
{{- define "soundings.envFrom" -}}
- configMapRef:
    name: {{ include "soundings.fullname" . }}
{{- with .Values.extraEnvFrom }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/* ---------------------------------------------------------------------------
Pods
--------------------------------------------------------------------------- */}}

{{/* Arguments of a container that waits until the database accepts connections. */}}
{{- define "soundings.waitForDatabaseArgs" -}}
- wait-for-db
- --timeout
- {{ .Values.migrations.waitForDatabaseSeconds | quote }}
{{- end }}

{{- define "soundings.volumeMounts" -}}
- name: tmp
  mountPath: /tmp
{{- if and .Values.smtp.host .Values.smtp.caBundle.configMap }}
- name: smtp-ca
  mountPath: /etc/soundings/smtp-ca
  readOnly: true
{{- end }}
{{- with .Values.extraVolumeMounts }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "soundings.volumes" -}}
- name: tmp
  emptyDir:
    sizeLimit: {{ .Values.tmpSizeLimit }}
{{- if and .Values.smtp.host .Values.smtp.caBundle.configMap }}
- name: smtp-ca
  configMap:
    name: {{ .Values.smtp.caBundle.configMap }}
    items:
      - key: {{ .Values.smtp.caBundle.key }}
        path: {{ .Values.smtp.caBundle.key }}
{{- end }}
{{- with .Values.extraVolumes }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/* Scheduling fields shared by every app pod. */}}
{{- define "soundings.scheduling" -}}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Init containers for api/worker pods. With the bundled Postgres the pods migrate the
schema themselves (after waiting for the database); see README "Migrations".
*/}}
{{- define "soundings.appInitContainers" -}}
{{- if .Values.postgresql.enabled }}
initContainers:
  {{- include "soundings.databaseContainer" (dict "ctx" . "name" "wait-for-db" "args" (include "soundings.waitForDatabaseArgs" .)) | nindent 2 }}
  {{- include "soundings.databaseContainer" (dict "ctx" . "name" "migrate" "args" "- migrate") | nindent 2 }}
{{- end }}
{{- end }}

{{/*
A container of the app image that only needs the database settings (ConfigMap) and
password: wait-for-db, migrate, seed.
Usage: include "soundings.databaseContainer" (dict "ctx" $ "name" "migrate" "args" "- migrate")
*/}}
{{- define "soundings.databaseContainer" -}}
{{- $ctx := .ctx -}}
- name: {{ .name }}
  image: {{ include "soundings.image" $ctx }}
  imagePullPolicy: {{ $ctx.Values.image.pullPolicy }}
  args:
    {{- .args | nindent 4 }}
  envFrom:
    {{- include "soundings.envFrom" $ctx | nindent 4 }}
  {{- with (include "soundings.databaseEnv" $ctx | trim) }}
  env:
    {{- . | nindent 4 }}
  {{- end }}
  resources:
    {{- toYaml $ctx.Values.migrations.resources | nindent 4 }}
  securityContext:
    {{- toYaml $ctx.Values.securityContext | nindent 4 }}
  volumeMounts:
    {{- include "soundings.volumeMounts" $ctx | nindent 4 }}
{{- end }}

{{/*
env and volume mounts of the migration hook Job (external database only): settings
inline and the database password from externalDatabase.existingSecret or the
"<fullname>-migrate" hook Secret, because hooks run before the release's ConfigMap and
Secret exist. Migrations need no other secret.
*/}}
{{- define "soundings.migrateEnv" -}}
{{- $hookSecret := printf "%s-migrate" (include "soundings.fullname" .) -}}
{{- range $name, $value := (include "soundings.configEnv" . | fromYaml) }}
- name: {{ $name }}
  value: {{ $value | quote }}
{{- end }}
{{- if .Values.externalDatabase.existingSecret }}
- name: SOUNDINGS_DATABASE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalDatabase.existingSecret }}
      key: {{ .Values.externalDatabase.existingSecretPasswordKey }}
{{- else if .Values.externalDatabase.password }}
- name: SOUNDINGS_DATABASE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ $hookSecret }}
      key: database-password
{{- end }}
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "soundings.migrateVolumeMounts" -}}
- name: tmp
  mountPath: /tmp
{{- with .Values.extraVolumeMounts }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/* ---------------------------------------------------------------------------
Validation (errors a JSON schema cannot express)
--------------------------------------------------------------------------- */}}
{{- define "soundings.validate" -}}
{{- if and (not .Values.postgresql.enabled) (not .Values.externalDatabase.host) }}
{{- fail "externalDatabase.host is required when postgresql.enabled=false" }}
{{- end }}
{{- if and .Values.smtp.host (not .Values.smtp.from) }}
{{- fail "smtp.from is required when smtp.host is set" }}
{{- end }}
{{- if and .Values.oidc.issuer (not (or .Values.oidc.clientSecret .Values.oidc.existingSecret)) }}
{{- fail "oidc.clientSecret or oidc.existingSecret is required when oidc.issuer is set" }}
{{- end }}
{{- if and .Values.httpRoute.enabled (not .Values.httpRoute.parentRefs) }}
{{- fail "httpRoute.parentRefs is required when httpRoute.enabled=true" }}
{{- end }}
{{- if and .Values.demo.seed (not .Values.devLogin) }}
{{- fail "demo.seed needs devLogin=true: demo data is only loaded in development mode" }}
{{- end }}
{{- if and .Values.autoscaling.enabled (lt (int .Values.autoscaling.maxReplicas) (int .Values.autoscaling.minReplicas)) }}
{{- fail "autoscaling.maxReplicas must be >= autoscaling.minReplicas" }}
{{- end }}
{{- end }}
