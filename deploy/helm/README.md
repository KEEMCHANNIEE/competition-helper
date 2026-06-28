# contest-helper Helm 차트 — 초보자용 단계별 가이드

이 문서는 **쿠버네티스(k8s)를 처음 만지는 사람**을 위해, 로컬에 가짜 클러스터
(`kind`)를 만들고 contest-helper 를 Helm 으로 배포하는 전 과정을 한 줄씩 설명한다.

> 큰 그림: `kind`(노트북 안의 작은 k8s) 만들기 → 도커 이미지 빌드 → 이미지를
> kind 안으로 넣기 → `helm install` 로 배포 → `port-forward` 로 브라우저 접속.

---

## 0. 준비물 (한 번만 설치)

| 도구 | 용도 | 설치(macOS, Homebrew) |
|------|------|----------------------|
| Docker Desktop | 컨테이너 실행 | https://www.docker.com/ |
| kind | 노트북 안의 k8s 클러스터 | `brew install kind` |
| kubectl | k8s 제어 CLI | `brew install kubectl` |
| helm | 차트 설치 도구 | `brew install helm` |

설치 확인:
```bash
docker version && kind version && kubectl version --client && helm version
```

---

## 1. kind 클러스터 만들기

```bash
# "contest-helper" 라는 이름의 1노드 클러스터 생성 (몇 분 걸림)
kind create cluster --name contest-helper

# kubectl 이 이 클러스터를 보고 있는지 확인 (노드 1개가 Ready 면 성공)
kubectl get nodes
```

---

## 2. 도커 이미지 빌드 (레포 루트에서!)

> ★ 가장 중요: 빌드 컨텍스트는 **레포 루트**다. (uv workspace 의 `libs/contest_helper_core`
> 를 COPY 해야 하기 때문) 아래 명령의 마지막 `.` 이 "컨텍스트=현재 폴더(루트)"라는 뜻.

```bash
cd /path/to/contest-helper   # 레포 루트로 이동

# api 이미지
docker build -f deploy/docker/api.Dockerfile -t contest-helper-api:dev .
# worker 이미지
docker build -f deploy/docker/worker.Dockerfile -t contest-helper-worker:dev .
# web 이미지 (services/web 이 존재할 때. 없으면 이 단계 건너뛰고 values 에서 web replica 0)
docker build -f deploy/docker/web.Dockerfile -t contest-helper-web:dev .
```

---

## 3. 이미지를 kind 클러스터 안으로 넣기

kind 는 노트북의 도커 이미지를 자동으로 못 본다. 명시적으로 "적재(load)"해야 한다.

```bash
kind load docker-image contest-helper-api:dev    --name contest-helper
kind load docker-image contest-helper-worker:dev --name contest-helper
kind load docker-image contest-helper-web:dev    --name contest-helper
```

---

## 4. (이 차트에 없는) App DB 준비

이 차트는 학습 단순화를 위해 **Postgres 를 포함하지 않는다**(Redis 만 포함).
DB 는 둘 중 하나로 준비한다:

- (간단) bitnami postgres 차트로 pgvector 가능한 DB 를 따로 설치, 또는
- (학습) `kubectl run` 으로 임시 pgvector Pod 를 띄우기:

```bash
kubectl run pg --image=pgvector/pgvector:pg16 \
  --env=POSTGRES_USER=contest_helper --env=POSTGRES_PASSWORD=contest_helper --env=POSTGRES_DB=contest_helper \
  --port=5432
kubectl expose pod pg --port=5432 --name=pg
# 그러면 클러스터 안 접속 URL: postgresql+psycopg://contest_helper:contest_helper@pg:5432/contest_helper
```

> ⚠️ 마이그레이션이 pgvector 를 쓰므로, 첫 alembic 리비전에서
> `CREATE EXTENSION IF NOT EXISTS vector` 가 실행돼야 한다(이미지에 확장은 들어있음).

---

## 5. Helm 으로 설치

```bash
# 차트 폴더로 이동
cd deploy/helm/contest-helper

# 설치(릴리스 이름 = contest-helper). 이미지 태그와 비밀값을 --set 으로 주입.
helm install contest-helper . \
  --set image.api.repository=contest-helper-api    --set image.api.tag=dev \
  --set image.worker.repository=contest-helper-worker --set image.worker.tag=dev \
  --set image.web.repository=contest-helper-web    --set image.web.tag=dev \
  --set secret.appDbUrl='postgresql+psycopg://contest_helper:contest_helper@pg:5432/contest_helper' \
  --set secret.geminiApiKey="$GEMINI_API_KEY" \
  --set secret.sessionSecret='change-me-please'
```

설치 미리보기(실제 적용 없이 렌더링만 확인):
```bash
helm template contest-helper . | less        # 생성될 YAML 전체 보기
helm install contest-helper . --dry-run --debug   # 서버 검증까지
```

배포 상태 확인:
```bash
kubectl get pods          # 모든 Pod 가 Running / READY 1/1 이 목표
kubectl get svc           # 서비스 목록
kubectl logs deploy/contest-helper-contest-helper-api      # api 로그(마이그레이션 결과 등)
kubectl logs deploy/contest-helper-contest-helper-worker   # worker 로그
```

---

## 6. 브라우저에서 접속 (port-forward)

Ingress 컨트롤러를 따로 안 깔았다면, 가장 쉬운 방법은 `port-forward` 다.

```bash
# api 를 로컬 8000 으로
kubectl port-forward svc/contest-helper-contest-helper-api 8000:8000
# 다른 터미널에서 web 을 로컬 8080 으로
kubectl port-forward svc/contest-helper-contest-helper-web 8080:80
```
이제 http://localhost:8000/health , http://localhost:8080 접속.

### (선택) Ingress 로 접속하기
```bash
# kind 에 ingress-nginx 설치
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
# /etc/hosts 에 추가:  127.0.0.1 contest-helper.local
# 그러면 http://contest-helper.local/ (web), http://contest-helper.local/api (api)
```

---

## 7. 업그레이드 / 삭제

```bash
# 이미지 태그만 바꿔 재배포(무중단 롤링)
helm upgrade contest-helper . --set image.api.tag=dev2 --reuse-values

# 전부 삭제
helm uninstall contest-helper
# 클러스터 자체 삭제
kind delete cluster --name contest-helper
```

---

## 자주 막히는 곳

- **ImagePullBackOff**: 이미지를 kind 에 `kind load` 안 했거나 태그가 안 맞음.
  → 3단계 다시. `image.pullPolicy=IfNotPresent`(기본값) 확인.
- **api Pod 가 CrashLoopBackOff**: 보통 DB 연결 실패(마이그레이션 단계).
  → `kubectl logs` 로 확인, `secret.appDbUrl` 호스트가 클러스터 안에서 닿는지 점검.
- **worker 가 아무것도 안 함**: 정상일 수 있음(큐가 비면 대기). api 로 추천 요청을
  넣어 큐에 작업이 들어가야 worker 가 움직인다.
- **secret 값이 안 들어감**: `--set secret.xxx=` 키 이름을 values.yaml 의 secret 키와
  정확히 맞출 것. 확인: `kubectl get secret contest-helper-contest-helper-secret -o yaml`.
