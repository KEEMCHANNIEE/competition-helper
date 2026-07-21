# =============================================================================
# web.Dockerfile — contest-helper의 React SPA(프론트엔드) 이미지
# =============================================================================
# 이 파일이 무엇인가:
#   - services/web (React + Vite + TypeScript) 를 "빌드"한 뒤,
#     결과물(정적 HTML/JS/CSS)을 가벼운 nginx 로 "서빙"한다.
#   - 멀티스테이지 빌드: ① node 로 빌드 → ② nginx 로 서빙.
#     빌드 도구(node, node_modules)는 최종 이미지에 포함되지 않아 매우 가볍다.
#
# ★ 빌드 컨텍스트 주의 ★
#   nginx.conf 를 deploy/docker/ 에서 COPY 해야 하므로, 컨텍스트는 api/worker 와
#   똑같이 "레포 루트" 여야 한다(services/web 를 컨텍스트로 잡으면 nginx.conf 가 안 보임).
#       docker build -f deploy/docker/web.Dockerfile -t contest-helper-web .
#                                                                        ^ 마지막 점(.) = 컨텍스트 = 레포 루트
#   (compose 에서는 build.context: .. 로 지정)
# =============================================================================

# ----- 1단계(build): node 로 프론트엔드 정적 산출물 생성 -----
FROM node:20-alpine AS build

WORKDIR /app

# package.json/lock 만 먼저 복사 → 의존성 레이어 캐시 활용
#   (소스만 바뀌면 npm ci 를 다시 안 해도 됨 = 빌드 빨라짐)
COPY services/web/package*.json ./
# npm ci: lockfile 기준으로 정확히 설치(재현 가능). lock 이 없으면 npm install 로 바꿀 것.
RUN npm ci

# 나머지 소스 복사 후 빌드. Vite 는 기본적으로 dist/ 에 결과물을 만든다.
COPY services/web/ .
RUN npm run build

# ----- 2단계(serve): nginx 로 정적 파일 서빙 -----
FROM nginx:alpine AS serve

# 우리가 만든 SPA 라우팅 설정으로 기본 설정을 교체.
#   (새로고침 시 /recommend 같은 경로에서 404 가 나지 않도록 fallback 처리)
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf

# 1단계에서 빌드한 정적 산출물(dist)을 nginx 가 서빙하는 폴더로 복사.
COPY --from=build /app/dist /usr/share/nginx/html

# nginx 는 80 포트로 서빙.
EXPOSE 80

# nginx 를 포그라운드로 실행(컨테이너가 살아있도록 daemon off).
CMD ["nginx", "-g", "daemon off;"]
