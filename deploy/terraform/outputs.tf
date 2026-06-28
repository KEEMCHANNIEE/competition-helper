# =============================================================================
# outputs.tf — apply 후 화면에 출력할 "결과 값들"
# =============================================================================
# terraform apply 가 끝나면 여기 정의한 값들이 출력된다.
# kubectl 연결, 이미지 push 주소, DB 접속에 바로 쓸 수 있어 편하다.
# (sensitive=true 인 값은 가려져 나오며 `terraform output -raw 이름` 으로 확인)
# =============================================================================

output "cluster_name" {
  description = "생성된 GKE 클러스터 이름"
  value       = google_container_cluster.primary.name
}

output "gke_get_credentials_command" {
  description = "kubectl 을 이 클러스터에 연결하는 명령(복붙용)"
  value       = "gcloud container clusters get-credentials ${google_container_cluster.primary.name} --zone ${var.zone} --project ${var.project_id}"
}

output "artifact_registry_repo" {
  description = "도커 이미지를 push 할 Artifact Registry 주소 prefix"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

output "sql_instance_connection_name" {
  description = "Cloud SQL 연결 이름(Cloud SQL Proxy 등에서 사용)"
  value       = google_sql_database_instance.postgres.connection_name
}

output "sql_public_ip" {
  description = "Cloud SQL 공인 IP (App DB 접속용)"
  value       = google_sql_database_instance.postgres.public_ip_address
}

output "app_db_url_hint" {
  description = "APP_DB_URL 형식 힌트(비밀번호는 직접 채워 넣을 것)"
  value       = "postgresql+psycopg://${var.db_user}:<password>@${google_sql_database_instance.postgres.public_ip_address}:5432/${var.db_name}"
  sensitive   = false
}
