{{/*
=============================================================================
_helpers.tpl — 템플릿에서 재사용하는 "함수(헬퍼)" 모음
=============================================================================
이 파일은 k8s 리소스를 직접 만들지 않는다. 대신 여러 템플릿이 공통으로 쓰는
이름/라벨 생성 로직을 define 으로 정의해 둔다. ({{ include "keenee.fullname" . }} 처럼 호출)
이렇게 하면 이름 규칙을 한 곳에서 관리할 수 있다.
=============================================================================
*/}}

{{/* 차트 기본 이름 (nameOverride 로 덮어쓸 수 있음) */}}
{{- define "keenee.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
전체 이름(fullname): 보통 "<릴리스명>-<차트명>".
모든 리소스 이름의 접두어로 쓰여 한 클러스터 안 충돌을 방지한다.
*/}}
{{- define "keenee.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "keenee.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
공통 라벨: 모든 리소스에 붙여 "이게 어느 앱/릴리스/차트 소속인지" 표시.
kubectl get all -l app.kubernetes.io/instance=<릴리스> 로 묶어 볼 수 있다.
*/}}
{{- define "keenee.labels" -}}
app.kubernetes.io/name: {{ include "keenee.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/*
컴포넌트(api/worker/web/redis)별 선택자 라벨.
Deployment 가 자기 Pod 를, Service 가 자기 대상 Pod 를 고르는 데 쓴다.
호출: {{ include "keenee.selectorLabels" (dict "ctx" . "component" "api") }}
*/}}
{{- define "keenee.selectorLabels" -}}
app.kubernetes.io/name: {{ include "keenee.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Secret 리소스의 표준 이름 */}}
{{- define "keenee.secretName" -}}
{{- printf "%s-secret" (include "keenee.fullname" .) -}}
{{- end -}}

{{/* ConfigMap 리소스의 표준 이름 */}}
{{- define "keenee.configmapName" -}}
{{- printf "%s-config" (include "keenee.fullname" .) -}}
{{- end -}}
