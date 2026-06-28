# =============================================================================
# main.tf — GCP 인프라를 코드로 정의 (GKE + Cloud SQL + Artifact Registry + VPC)
# =============================================================================
# 🟡 보너스 단계. 이 파일 하나로 keenee 를 운영할 클라우드 자원을 통째로 만든다.
#   - VPC               : 자원들이 들어갈 사설 네트워크
#   - Artifact Registry : 도커 이미지 저장소(CD 가 여기에 push)
#   - GKE (Spot)        : 쿠버네티스 클러스터(저렴한 Spot e2-small 노드)
#   - Cloud SQL Postgres: App DB (pgvector 확장은 생성 후 직접 활성화)
#
# ★ 비용 주의 ★ GKE/Cloud SQL 은 "켜져 있는 동안" 과금된다.
#   학습이 끝나면 반드시 `terraform destroy` 로 내려서 크레딧을 아낄 것.
#   (자세한 운영법은 같은 폴더의 README.md 참고)
# =============================================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  # (선택) 상태 파일을 GCS 버킷에 원격 저장하려면 backend "gcs" 블록 추가.
  # 팀 작업/CD 에서는 권장. 혼자 학습이면 로컬 terraform.tfstate 로도 충분.
}

# GCP provider: 어떤 프로젝트/리전에 자원을 만들지 지정.
provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# -----------------------------------------------------------------------------
# 0) 필요한 GCP API 활성화
# -----------------------------------------------------------------------------
# 새 프로젝트는 API 가 꺼져 있어 자원 생성이 거부된다. 미리 켜둔다.
resource "google_project_service" "services" {
  for_each = toset([
    "container.googleapis.com",        # GKE
    "sqladmin.googleapis.com",         # Cloud SQL
    "artifactregistry.googleapis.com", # Artifact Registry
    "compute.googleapis.com",          # VPC/네트워크/디스크
    "servicenetworking.googleapis.com" # Cloud SQL 사설 연결(선택)
  ])
  service            = each.value
  disable_on_destroy = false # destroy 시 API 까지 끄지는 않음(다른 자원 영향 방지)
}

# -----------------------------------------------------------------------------
# 1) VPC 네트워크 + 서브넷
# -----------------------------------------------------------------------------
# 자원들이 통신할 사설 네트워크. auto 서브넷을 끄고 우리가 직접 하나 만든다.
resource "google_compute_network" "vpc" {
  name                    = "keenee-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.services]
}

resource "google_compute_subnetwork" "subnet" {
  name          = "keenee-subnet"
  ip_cidr_range = "10.10.0.0/16" # 노드/내부 IP 대역
  region        = var.region
  network       = google_compute_network.vpc.id

  # GKE Pod/Service 용 보조 IP 대역(VPC-native 클러스터에 필요).
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.20.0.0/16"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.30.0.0/16"
  }
}

# -----------------------------------------------------------------------------
# 2) Artifact Registry (도커 이미지 저장소)
# -----------------------------------------------------------------------------
# CD 파이프라인이 빌드한 api/worker/web 이미지를 여기에 push 한다.
# 이미지 주소 형식:
#   <region>-docker.pkg.dev/<project>/<repo>/<image>:<tag>
resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = var.artifact_repo_id
  format        = "DOCKER"
  description   = "keenee 컨테이너 이미지 저장소"
  depends_on    = [google_project_service.services]
}

# -----------------------------------------------------------------------------
# 3) GKE 클러스터 + Spot 노드 풀
# -----------------------------------------------------------------------------
# 비용 절감 패턴: 클러스터는 기본 노드 풀을 제거하고, 우리가 만든
# "작은 Spot 노드 풀" 하나만 붙인다.
resource "google_container_cluster" "primary" {
  name     = var.cluster_name
  location = var.zone # 존(zonal) 클러스터 = 리전 클러스터보다 저렴

  # 기본 노드 풀 제거 후 별도 풀 사용(권장 패턴).
  remove_default_node_pool = true
  initial_node_count       = 1

  network    = google_compute_network.vpc.id
  subnetwork = google_compute_subnetwork.subnet.id

  # VPC-native(별칭 IP): 위에서 만든 보조 대역 사용.
  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  deletion_protection = false # ★ destroy 가능하도록(학습용). 운영은 true 고려.
  depends_on          = [google_project_service.services]
}

resource "google_container_node_pool" "spot_nodes" {
  name       = "spot-pool"
  cluster    = google_container_cluster.primary.id
  node_count = var.node_count

  node_config {
    machine_type = var.node_machine_type # e2-small (저렴)
    spot         = var.use_spot_vms      # ★ Spot VM = 큰 폭 할인(중단 가능성 감수)
    disk_size_gb = 30                    # 작은 디스크로 비용 절감
    disk_type    = "pd-standard"         # 표준 디스크(SSD 보다 저렴)

    # 노드가 Artifact Registry pull, 로깅 등에 필요한 최소 권한.
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
}

# -----------------------------------------------------------------------------
# 4) Cloud SQL (Postgres 16) — App DB
# -----------------------------------------------------------------------------
# ★ pgvector 주의 ★ Cloud SQL 은 pgvector "확장 기능을 지원"하지만,
#   인스턴스를 만든다고 자동 활성화되진 않는다. DB 생성 후 한 번:
#     CREATE EXTENSION IF NOT EXISTS vector;
#   를 실행해야 한다(우리 alembic 첫 마이그레이션이 담당하게 하면 자동화됨).
resource "google_sql_database_instance" "postgres" {
  name             = "keenee-pg"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = var.db_tier        # db-f1-micro (가장 저렴)
    availability_type = "ZONAL"            # 단일 존(리전 HA 보다 저렴)
    disk_size         = 10                 # GB
    disk_autoresize   = false              # 자동 증설 끔(예기치 않은 과금 방지)

    backup_configuration {
      enabled = false # 학습용은 백업 끔(과금↓). 운영은 켤 것.
    }
    # 학습 단순화를 위해 공인 IP 허용(특정 IP 로 제한 권장).
    ip_configuration {
      ipv4_enabled = true
      # authorized_networks { name = "me"; value = "<내 공인 IP>/32" }  # 보안 강화 시
    }
  }

  deletion_protection = false # ★ destroy 가능(학습용)
  depends_on          = [google_project_service.services]
}

resource "google_sql_database" "app_db" {
  name     = var.db_name
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "app_user" {
  name     = var.db_user
  instance = google_sql_database_instance.postgres.name
  password = var.db_password # variables.tf 에서 sensitive 처리
}
