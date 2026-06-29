# contest-helper Terraform (GCP) — 단계별 + 비용 절감 운영법

🟡 **보너스 단계.** GCP 에 contest-helper 운영용 인프라(GKE + Cloud SQL + Artifact
Registry + VPC)를 코드로 만든다. **돈이 나가는 영역**이므로 "켜고 → 쓰고 →
반드시 끄기(destroy)" 흐름을 몸에 익히는 게 핵심이다.

---

## 💰 먼저 읽기: $300 무료 크레딧 & 비용 원칙

- 신규 GCP 계정은 보통 **$300 / 90일 무료 크레딧**을 준다. 학습은 이 안에서 충분.
- 그래도 **GKE 와 Cloud SQL 은 켜져 있는 동안 계속 과금**된다(시간당).
- 황금 규칙 3가지:
  1. **다 쓰면 즉시 `terraform destroy`** — 자는 동안 과금되지 않게.
  2. **작게 쓰기** — 이 설정은 이미 Spot `e2-small` + `db-f1-micro` 로 최소화.
  3. **예산 알림 설정** — 콘솔 > 결제 > 예산 및 알림에서 $10 등으로 알림 걸기.

> Spot VM 은 매우 저렴하지만 구글이 자원을 회수하면 노드가 갑자기 죽을 수 있다.
> 학습/배치성 워크로드엔 괜찮지만, 그래서 운영 DB 는 Cloud SQL(별도)로 분리했다.

---

## 0. 준비물

| 도구 | 설치 |
|------|------|
| gcloud CLI | https://cloud.google.com/sdk/docs/install |
| terraform | `brew install terraform` |

로그인 + 기본 프로젝트 설정:
```bash
gcloud auth login
gcloud auth application-default login   # ★ terraform 이 쓰는 인증
gcloud config set project <YOUR_PROJECT_ID>
```

---

## 1. 입력 값 준비 (terraform.tfvars)

같은 폴더에 `terraform.tfvars` 파일을 만들고 채운다. **이 파일은 git 에 올리지 말 것**
(비밀번호 포함). `.gitignore` 에 `*.tfvars` 추가 권장.

```hcl
project_id  = "my-contest-helper-123456"
region      = "asia-northeast3"
zone        = "asia-northeast3-a"
db_password = "강력한-비밀번호-여기"
# 나머지는 variables.tf 의 기본값 사용(원하면 덮어쓰기)
```

---

## 2. 만들기 (apply)

```bash
cd deploy/terraform

terraform init      # 프로바이더(플러그인) 내려받기 (한 번만)
terraform plan      # ★ 무엇이 만들어질지 미리보기 (과금 자원 확인!)
terraform apply     # yes 입력하면 실제 생성 (5~15분 소요)
```

apply 가 끝나면 출력(outputs)에서 연결 명령이 나온다:
```bash
# kubectl 을 GKE 에 연결
$(terraform output -raw gke_get_credentials_command)
kubectl get nodes   # Spot 노드가 Ready 면 성공

# 이미지 push 주소 확인
terraform output artifact_registry_repo
# Cloud SQL 공인 IP 확인
terraform output sql_public_ip
```

---

## 3. 이미지 push → Helm 배포 (요약)

```bash
# 도커가 Artifact Registry 에 push 할 수 있게 인증
gcloud auth configure-docker asia-northeast3-docker.pkg.dev

REPO=$(terraform output -raw artifact_registry_repo)
# 레포 루트에서 빌드 후 태그 붙여 push
docker build -f deploy/docker/api.Dockerfile -t $REPO/api:v1 .
docker push $REPO/api:v1
# (worker, web 동일)

# Helm 설치 시 이미지 repo/tag 와 DB URL 을 GKE 에 맞게 주입
helm install contest-helper ../helm/contest-helper \
  --set image.api.repository=$REPO/api --set image.api.tag=v1 \
  --set secret.appDbUrl="postgresql+psycopg://contest-helper:<pw>@<sql_public_ip>:5432/contest_helper"
```

> pgvector: Cloud SQL 인스턴스에 접속해 `CREATE EXTENSION IF NOT EXISTS vector;`
> 를 한 번 실행해야 RAG 임베딩이 동작한다(우리 alembic 첫 마이그레이션이 하도록 해두면 자동).

---

## 4. ★ 끝나면 반드시 내리기 (destroy) ★

```bash
cd deploy/terraform
terraform destroy   # yes 입력 → 모든 과금 자원 삭제
```

부분만 끄고 싶다면(예: 비싼 GKE 만 잠깐 내리기):
```bash
terraform destroy -target=google_container_node_pool.spot_nodes
# 다시 쓸 때
terraform apply -target=google_container_node_pool.spot_nodes
```

---

## 자주 막히는 곳

- **API not enabled 오류**: 첫 apply 에서 API 활성화와 자원 생성이 동시에 일어나
  타이밍 이슈가 날 수 있다. → 잠시 후 `terraform apply` 재실행하면 대개 해결.
- **권한 오류**: `gcloud auth application-default login` 을 안 했거나 프로젝트 권한 부족.
- **destroy 가 막힘**: `deletion_protection = false` 인지 확인(이 코드는 false 로 둠).
- **요금이 계속 나옴**: `terraform state list` 로 남은 자원 확인 후 destroy.
  콘솔 결제 대시보드도 함께 점검.
