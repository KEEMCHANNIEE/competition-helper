# --- build stage ---
FROM node:20-alpine AS build
WORKDIR /app

# 의존성 캐시 레이어
COPY package.json package-lock.json* ./
RUN npm install

COPY . .
# VITE_API_BASE 는 런타임 nginx 프록시(/api)를 사용하므로 기본값으로 충분.
RUN npm run build

# --- serve stage ---
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
