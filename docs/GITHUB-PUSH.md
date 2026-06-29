# 깃허브에 올리는 방법

다른 노트북(삼성)에서 이 프로젝트를 GitHub에 올리는 절차.

---

## 0. 올라가는 파일 / 안 올라가는 파일

- ✅ 올라감: `services/`, `libs/`, `deploy/`, `docs/`, `.github/`, `README.md`, `pyproject.toml`, `.env.example` 등 (코드·문서·설정)
- ❌ 안 올라감(자동 제외, `.gitignore` 처리됨): `.env`(비밀값), `.venv/`, `node_modules/`, `__pycache__/`, `.omc/`, `.claude/`

→ **비밀값(`.env`)은 깃에 안 올라가니 안심.** 단, 폴더를 복사할 때 `.env` 파일 자체는 같이 복사돼도 됨(깃이 무시함).

---

## 1. 준비 (삼성 노트북에서)

1. **Git 설치** — https://git-scm.com/download/win (설치하면 "Git Bash" 생김)
2. **GitHub 계정** 로그인 → 우상단 **+ → New repository**
   - 이름: `contest-helper` (예시)
   - **Private 권장**
   - "Add a README" 등은 **체크하지 말 것** (비워서 생성)
   - Create → 나오는 주소 복사 (예: `https://github.com/내아이디/contest-helper.git`)

---

## 2. 폴더 옮기기

이 `keenee` 폴더(이름은 그대로여도 됨)를 삼성 노트북으로 복사한다.

- **가능하면 숨김 폴더 `.git` 까지 통째로** 복사 → 지금까지의 커밋 기록이 같이 간다. (아래 A 경로)
- `.git` 이 안 따라왔으면 새로 시작한다. (아래 B 경로)

> 압축(zip)해서 옮길 때: 숨김 파일 포함해서 압축하면 `.git`·`.env` 도 같이 간다.

---

## 3-A. `.git` 이 같이 온 경우 (권장)

Git Bash 에서 그 폴더로 이동 후:

```bash
cd /경로/contest-helper        # 폴더 위치로 이동
git remote add origin https://github.com/내아이디/contest-helper.git
git branch -M main
git push -u origin main
```
- 처음 push 시 GitHub 로그인 창이 뜨면 로그인.
- 끝! 브라우저에서 레포 새로고침하면 파일이 올라가 있다.

> 이미 remote 가 있다는 에러가 나면: `git remote set-url origin <주소>` 후 다시 push.

## 3-B. `.git` 이 없는 경우 (새로 시작)

```bash
cd /경로/contest-helper
git init -b main
git add .
git commit -m "init: contest-helper scaffold (1차 틀 작업)"
git remote add origin https://github.com/내아이디/contest-helper.git
git push -u origin main
```

---

## 4. 올린 뒤 — 팀원이 받기

팀원들은 각자:
```bash
git clone https://github.com/내아이디/contest-helper.git
cd contest-helper
cp .env.example .env          # 각자 .env 채우기 (비밀값은 따로 공유)
uv sync
```

---

## 자주 나는 문제

- **로그인 안 됨**: GitHub 는 비밀번호 대신 토큰을 쓴다. 로그인 창에서 브라우저 인증을 따르거나, Personal Access Token 발급(https://github.com/settings/tokens) 후 비밀번호 자리에 입력.
- **`.env` 가 올라갈까 걱정**: `.gitignore` 에 들어 있어 안 올라간다. 확인: `git status` 에 `.env` 가 안 보이면 정상.
- **`git push` 가 거부됨(rejected)**: 원격에 README 등이 먼저 있는 경우. 빈 레포로 다시 만들거나 `git pull --rebase origin main` 후 push.
