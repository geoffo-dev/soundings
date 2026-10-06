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

{{/* The SMTP port the app uses: smtp.port, or 465 for security tls and 587 otherwise. */}}
{{- define "soundings.smtpPort" -}}
{{- $port := toString .Values.smtp.port }}
{{- if $port }}{{ $port }}{{ else if eq .Values.smtp.security "tls" }}465{{ else }}587{{ end }}
{{- end }}

{{/* Port of an http(s) URL: the explicit one, else 443 for https and 80 for http. */}}
{{- define "soundings.urlPort" -}}
{{- $url := urlParse . }}
{{- $hostPort := splitList ":" $url.host }}
{{- if gt (len $hostPort) 1 }}{{ last $hostPort }}{{ else if eq $url.scheme "http" }}80{{ else }}443{{ end }}
{{- end }}

{{/* kagent's controller URL (A2A): kagent.controllerUrl, else kagent's chart default. */}}
{{- define "soundings.kagentUrl" -}}
{{- .Values.kagent.controllerUrl | default (printf "http://kagent-controller.%s:8083" (.Values.kagent.namespace | default "kagent")) }}
{{- end }}

{{/* Namespaces agents may be registered in: kagent.agentNamespaces, else the release's. */}}
{{- define "soundings.agentNamespaces" -}}
{{- .Values.kagent.agentNamespaces | default (list .Release.Namespace) | join "," }}
{{- end }}

{{/* The Service URL of /mcp (what agents' RemoteMCPServers use; shown to admins). */}}
{{- define "soundings.mcpServiceUrl" -}}
{{- printf "http://%s.%s.svc.cluster.local:%v/mcp" (include "soundings.fullname" .) .Release.Namespace .Values.service.port }}
{{- end }}

{{/* AI runs and kagent are in use: kagent's controller is reached (egress, token). */}}
{{- define "soundings.kagentInUse" -}}
{{- if or .Values.features.ai .Values.kagent.enabled }}true{{ end }}
{{- end }}

{{/* An example agent's (dict "ctx" $ "agent" "evaluator") name and key Secret. */}}
{{- define "soundings.exampleAgentName" -}}
{{- printf "%s-%s" (include "soundings.fullname" .ctx) .agent }}
{{- end }}

{{- define "soundings.exampleAgentKeySecret" -}}
{{- $values := index .ctx.Values.kagent.agents .agent }}
{{- $values.keySecret | default (printf "soundings-agent-%s" (include "soundings.exampleAgentName" .)) }}
{{- end }}

{{/*
A duration value (ISO 8601 such as PT12H, or a number of seconds) as the ISO 8601
string the app parses: 3600 -> PT3600S (the app reads only ISO 8601 durations).
*/}}
{{- define "soundings.duration" -}}
{{- if or (kindIs "float64" .) (kindIs "int" .) (kindIs "int64" .) }}
{{- printf "PT%dS" (int64 .) }}
{{- else if regexMatch "^[0-9]+$" (toString .) }}
{{- printf "PT%sS" (toString .) }}
{{- else }}
{{- . }}
{{- end }}
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
SOUNDINGS_TRUSTED_PROXY_HOPS: {{ .Values.trustedProxyHops | quote }}
SOUNDINGS_LOG_LEVEL: {{ .Values.logLevel | quote }}
SOUNDINGS_DATABASE_URL: {{ include "soundings.databaseUrl" . | quote }}
SOUNDINGS_METRICS_PORT: {{ .Values.metrics.port | quote }}
SOUNDINGS_SESSION_IDLE_TIMEOUT: {{ include "soundings.duration" .Values.sessions.idleTimeout | quote }}
SOUNDINGS_SESSION_MAX_AGE: {{ include "soundings.duration" .Values.sessions.maxAge | quote }}
SOUNDINGS_WORKER_CONCURRENCY: {{ .Values.worker.concurrency | quote }}
SOUNDINGS_PUBLIC_SUBMISSION_ENABLED: {{ .Values.features.publicSubmission | quote }}
SOUNDINGS_PUBLIC_SUBMISSIONS_PER_IP: {{ int .Values.publicSubmission.perIpPerHour | quote }}
SOUNDINGS_PUBLIC_SUBMISSIONS_PER_PROJECT: {{ int .Values.publicSubmission.perProjectPerHour | quote }}
SOUNDINGS_ALTCHA_COST: {{ int .Values.publicSubmission.altcha.cost | quote }}
SOUNDINGS_ALTCHA_EXPIRY: {{ include "soundings.duration" .Values.publicSubmission.altcha.expiry | quote }}
SOUNDINGS_BRANDING_MAX_UPLOAD_BYTES: {{ int .Values.branding.maxUploadBytes | quote }}
SOUNDINGS_AI_ENABLED: {{ .Values.features.ai | quote }}
SOUNDINGS_KAGENT_URL: {{ include "soundings.kagentUrl" . | quote }}
SOUNDINGS_AI_DEFAULT_PROTOCOL: {{ .Values.ai.defaultProtocol | quote }}
SOUNDINGS_AI_RUN_TIMEOUT: {{ include "soundings.duration" .Values.ai.runTimeout | quote }}
SOUNDINGS_AI_MAX_CONCURRENT_RUNS: {{ int .Values.ai.maxConcurrentRuns | quote }}
SOUNDINGS_AI_AGENT_NAMESPACES: {{ include "soundings.agentNamespaces" . | quote }}
SOUNDINGS_AI_MCP_URL: {{ .Values.ai.mcpUrl | default (include "soundings.mcpServiceUrl" .) | quote }}
SOUNDINGS_BREAK_GLASS_ENABLED: {{ .Values.breakGlass.enabled | quote }}
{{- with .Values.otel.endpoint }}
SOUNDINGS_OTEL_ENDPOINT: {{ . | quote }}
{{- end }}
{{- if .Values.oidc.issuer }}
SOUNDINGS_OIDC_ISSUER: {{ .Values.oidc.issuer | quote }}
SOUNDINGS_OIDC_CLIENT_ID: {{ .Values.oidc.clientId | quote }}
SOUNDINGS_OIDC_GROUPS_CLAIM: {{ .Values.oidc.groupsClaim | quote }}
SOUNDINGS_OIDC_SCOPES: {{ join "," .Values.oidc.scopes | quote }}
SOUNDINGS_OIDC_MATCH_VERIFIED_EMAIL: {{ .Values.oidc.matchVerifiedEmail | quote }}
SOUNDINGS_OIDC_AUTO_CREATE_USERS: {{ .Values.oidc.autoCreateUsers | quote }}
{{- with .Values.oidc.externalIdClaim }}
SOUNDINGS_OIDC_EXTERNAL_ID_CLAIM: {{ . | quote }}
{{- with $.Values.oidc.externalIdKind }}
SOUNDINGS_OIDC_EXTERNAL_ID_KIND: {{ . | quote }}
{{- end }}
{{- end }}
{{- end }}
SOUNDINGS_TIMEZONE: {{ .Values.timezone | quote }}
SOUNDINGS_DIGEST_HOUR: {{ .Values.notifications.digestHour | quote }}
SOUNDINGS_REMINDER_DAYS: {{ join "," .Values.notifications.reminderDays | quote }}
{{- if .Values.smtp.host }}
SOUNDINGS_SMTP_HOST: {{ .Values.smtp.host | quote }}
SOUNDINGS_SMTP_PORT: {{ include "soundings.smtpPort" . | quote }}
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
{{- /* Only the worker gets the credentials (soundings.secretEnv); the api shows these. */}}
{{- if or .Values.smtp.existingSecret .Values.smtp.username }}
SOUNDINGS_SMTP_USERNAME_SET: "true"
{{- end }}
{{- if or .Values.smtp.existingSecret .Values.smtp.password }}
SOUNDINGS_SMTP_PASSWORD_SET: "true"
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

{{/*
Secrets of the api and worker pods: (dict "ctx" . "signIn" true) for the api (the sign-in
secrets), (dict "ctx" . "smtp" true) for the worker (the SMTP credentials: only the
worker sends mail; the api gets SOUNDINGS_SMTP_*_SET flags in the ConfigMap instead).
Both get kagent's controller token (kagent.existingTokenSecret): the api for test
connection, the worker for runs.
*/}}
{{- define "soundings.secretEnv" -}}
{{- $signIn := .signIn -}}
{{- $smtp := .smtp -}}
{{- with .ctx -}}
{{- $fullname := include "soundings.fullname" . -}}
- name: SOUNDINGS_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "soundings.secretKey.secretName" . }}
      key: {{ include "soundings.secretKey.key" . }}
{{- include "soundings.databasePasswordEnv" . }}
{{- if $signIn }}
{{- include "soundings.signInSecretEnv" . }}
{{- end }}
{{- if and (include "soundings.kagentInUse" .) .Values.kagent.existingTokenSecret }}
- name: SOUNDINGS_KAGENT_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.kagent.existingTokenSecret }}
      key: {{ .Values.kagent.tokenSecretKey }}
{{- end }}
{{- if and $smtp .Values.smtp.host }}
{{- if .Values.smtp.existingSecret }}
- name: SOUNDINGS_SMTP_USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ .Values.smtp.existingSecret }}
      key: username
- name: SOUNDINGS_SMTP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.smtp.existingSecret }}
      key: password
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
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Sign-in secrets, for the api pods only (the worker never signs anyone in): the OIDC
client secret, and the break-glass credentials. The app ignores the latter while
oidc.issuer is set; they stay wired so that unsetting the issuer in an SSO outage
brings back the same account.
*/}}
{{- define "soundings.signInSecretEnv" -}}
{{- $fullname := include "soundings.fullname" . -}}
{{- if and .Values.oidc.issuer (or .Values.oidc.existingSecret .Values.oidc.clientSecret) }}
- name: SOUNDINGS_OIDC_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ .Values.oidc.existingSecret | default $fullname }}
      key: {{ ternary .Values.oidc.existingSecretKey "oidc-client-secret" (not (empty .Values.oidc.existingSecret)) }}
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
Egress (networkPolicy.egress.enabled)
--------------------------------------------------------------------------- */}}

{{/*
Egress rules of the api or worker pods: DNS, the database, the worker's SMTP server,
the api's IdP, kagent's controller (both, with features.ai or kagent.enabled), the OTLP
endpoint, then networkPolicy.egress.extra. A destination's `to`
peers, when empty, mean any address (on that port only).
Usage: include "soundings.egressRules" (dict "ctx" $ "component" "worker")
*/}}
{{- define "soundings.egressRules" -}}
{{- $ctx := .ctx -}}
{{- $egress := $ctx.Values.networkPolicy.egress -}}
- ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
{{- if $ctx.Values.postgresql.enabled }}
- to:
    - podSelector:
        matchLabels:
          {{- include "soundings.componentSelectorLabels" (dict "ctx" $ctx "component" "postgresql") | nindent 10 }}
  ports:
    - port: 5432
      protocol: TCP
{{- else }}
- ports:
    - port: {{ int $ctx.Values.externalDatabase.port }}
      protocol: TCP
  {{- with $egress.database.to }}
  to:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
{{- if and (eq .component "worker") $ctx.Values.smtp.host }}
- ports:
    - port: {{ int (toString $egress.smtp.port | default (include "soundings.smtpPort" $ctx)) }}
      protocol: TCP
  {{- with $egress.smtp.to }}
  to:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
{{- if and (eq .component "api") $ctx.Values.oidc.issuer }}
- ports:
    - port: {{ int (toString $egress.oidc.port | default (include "soundings.urlPort" $ctx.Values.oidc.issuer)) }}
      protocol: TCP
  {{- with $egress.oidc.to }}
  to:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
{{- if include "soundings.kagentInUse" $ctx }}
- ports:
    - port: {{ int (toString $egress.kagent.port | default (include "soundings.urlPort" (include "soundings.kagentUrl" $ctx))) }}
      protocol: TCP
  {{- with $egress.kagent.to }}
  to:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
{{- with $ctx.Values.otel.endpoint }}
- ports:
    - port: {{ int (include "soundings.urlPort" .) }}
      protocol: TCP
{{- end }}
{{- with $egress.extra }}
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
{{- if and .Values.smtp.existingSecret (or .Values.smtp.username .Values.smtp.password) }}
{{- fail "set the SMTP credentials either in smtp.existingSecret or in smtp.username / smtp.password, not both" }}
{{- end }}
{{- if and .Values.smtp.host (or .Values.smtp.password .Values.smtp.existingSecret) (eq .Values.smtp.security "none") (not .Values.devLogin) }}
{{- fail "smtp.security none sends the SMTP password in clear text: use starttls or tls (production refuses it)" }}
{{- end }}
{{- with toString .Values.smtp.port }}
{{- if gt (int .) 65535 }}
{{- fail "smtp.port must be between 1 and 65535" }}
{{- end }}
{{- end }}
{{- if and .Values.oidc.issuer (not (or .Values.oidc.clientSecret .Values.oidc.existingSecret)) }}
{{- fail "oidc.clientSecret or oidc.existingSecret is required when oidc.issuer is set" }}
{{- end }}
{{- /* Production mode (devLogin off) refuses these at startup; say so before installing. */}}
{{- if and .Values.oidc.issuer (not .Values.devLogin) }}
{{- if not (hasPrefix "https://" .Values.oidc.issuer) }}
{{- fail "oidc.issuer must be an https URL (only devLogin installs may use http)" }}
{{- end }}
{{- range .Values.baseUrls }}
{{- if not (hasPrefix "https://" .) }}
{{- fail (printf "baseUrls must all be https when SSO is configured (sign-in redirects carry the authorization code): %s" .) }}
{{- end }}
{{- end }}
{{- end }}
{{- if and .Values.oidc.externalIdKind (not .Values.oidc.externalIdClaim) }}
{{- fail "oidc.externalIdKind needs oidc.externalIdClaim" }}
{{- end }}
{{- if and .Values.oidc.externalIdClaim (not .Values.oidc.externalIdKind) }}
{{- if not (regexMatch "^[a-z][a-z0-9_]{0,39}$" (.Values.oidc.externalIdClaim | splitList "." | last)) }}
{{- fail "oidc.externalIdKind is required when the last segment of oidc.externalIdClaim is not a kind (lower-case letters, digits, underscores)" }}
{{- end }}
{{- end }}
{{- if and .Values.httpRoute.enabled (not .Values.httpRoute.parentRefs) }}
{{- fail "httpRoute.parentRefs is required when httpRoute.enabled=true" }}
{{- end }}
{{- if and .Values.kagent.enabled (not .Values.kagent.namespace) }}
{{- fail "kagent.namespace is required when kagent.enabled=true" }}
{{- end }}
{{- if and .Values.kagent.examples (not .Values.kagent.enabled) }}
{{- fail "kagent.examples needs kagent.enabled=true (and kagent's CRDs in the cluster)" }}
{{- end }}
{{- if and .Values.kagent.examples (or .Values.kagent.agents.evaluator.enabled .Values.kagent.agents.researcher.enabled) (not .Values.kagent.agents.modelConfig) }}
{{- fail "kagent.agents.modelConfig is required with kagent.examples: the name of an existing kagent ModelConfig in the release namespace (or turn off kagent.agents.evaluator.enabled and .researcher.enabled)" }}
{{- end }}
{{- if and .Values.kagent.examples .Values.kagent.agentNamespaces (not (has .Release.Namespace .Values.kagent.agentNamespaces)) }}
{{- fail (printf "kagent.examples renders its agents in the release namespace (%s): add it to kagent.agentNamespaces, or they can't be registered" .Release.Namespace) }}
{{- end }}
{{- if and .Values.kagent.existingTokenSecret (not .Values.kagent.tokenSecretKey) }}
{{- fail "kagent.tokenSecretKey is required with kagent.existingTokenSecret" }}
{{- end }}
{{- if and .Values.demo.seed (not .Values.devLogin) }}
{{- fail "demo.seed needs devLogin=true: demo data is only loaded in development mode" }}
{{- end }}
{{- if and .Values.autoscaling.enabled (lt (int .Values.autoscaling.maxReplicas) (int .Values.autoscaling.minReplicas)) }}
{{- fail "autoscaling.maxReplicas must be >= autoscaling.minReplicas" }}
{{- end }}
{{- end }}
