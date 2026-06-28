# =============================================================================
# variables.tf — Terraform 입력 변수 (환경마다 바꾸는 값)
# =============================================================================
# Terraform 은 "원하는 클라우드 상태"를 코드로 적고(apply) 그대로 만들어준다.
# 여기 변수들은 main.tf 가 쓰는 "다이얼"이다. 실제 값은
#   - terraform.tfvars 파일, 또는
#   - terraform apply -var="project_id=..." 로 주입.
# (project_id 처럼 사람마다 다른 값은 기본값 없이 두어 빠뜨림을 방지)
# =============================================================================

variable "project_id" {
  description = "GCP 프로젝트 ID (예: my-contest-helper-123456). $300 무료 크레딧 프로젝트 권장."
  type        = string
}

variable "region" {
  description = "GCP 리전. 한국이면 asia-northeast3(서울)."
  type        = string
  default     = "asia-northeast3"
}

variable "zone" {
  description = "GKE 노드가 뜰 존(영역). 리전 안의 한 구역."
  type        = string
  default     = "asia-northeast3-a"
}

variable "cluster_name" {
  description = "GKE 클러스터 이름."
  type        = string
  default     = "contest-helper-gke"
}

# --- 비용 절감 핵심: 작은 Spot 노드 ---
variable "node_machine_type" {
  description = "노드 머신 타입. e2-small(2 vCPU 공유, 2GB)로 비용 최소화."
  type        = string
  default     = "e2-small"
}

variable "node_count" {
  description = "노드 풀의 노드 수. 학습용은 1~2개면 충분."
  type        = number
  default     = 1
}

variable "use_spot_vms" {
  description = "Spot(선점형) VM 사용 여부. true 면 최대 60~91% 저렴(단, 중단될 수 있음)."
  type        = bool
  default     = true
}

# --- Cloud SQL (Postgres + pgvector) ---
variable "db_tier" {
  description = "Cloud SQL 머신 등급. db-f1-micro 가 가장 저렴(학습용)."
  type        = string
  default     = "db-f1-micro"
}

variable "db_name" {
  description = "생성할 App DB 이름."
  type        = string
  default     = "contest_helper"
}

variable "db_user" {
  description = "App DB 사용자."
  type        = string
  default     = "contest_helper"
}

variable "db_password" {
  description = "App DB 비밀번호. ★ tfvars 나 -var 로 주입하고 git 에 커밋 금지 ★"
  type        = string
  sensitive   = true # 로그/출력에 마스킹
}

# --- Artifact Registry (도커 이미지 저장소) ---
variable "artifact_repo_id" {
  description = "Artifact Registry 도커 저장소 이름."
  type        = string
  default     = "contest_helper"
}
