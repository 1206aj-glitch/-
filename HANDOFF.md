# 인수인계서 — 하늘스크린교회 말씀 아카이브 (2026-11-05 기준)

> 이 파일은 Claude Code가 이 폴더에서 작업을 시작할 때 자동으로 읽습니다. 사용자(장정호)와는 한국어로 대화합니다.
> 사용자는 "자동으로 돌아가는 것"을 가장 중요하게 여깁니다. 손으로 매번 해야 하는 방식은 피하세요.

---

## 1. 지금 이 폴더에서 할 일 (최우선)

**네이버 밴드의 예배 영상을 매주 1회, 아직 받지 않은 것만 이 폴더에 내려받는 자동화**를 PC에 만드는 것.

- 이 폴더: `G:\내 드라이브\하늘스크린교회 밴드 설교영상` (구글 드라이브 데스크톱으로 동기화 → 넣으면 자동 업로드)
- 이미 들어 있는 파일
  - `읽어주세요.txt` — 폴더 안내
  - `band_downloaded.json` — 받은 영상 기록 장부. 형식: `{"downloaded": [ {"key": "<밴드 글/영상 고유값>", "file": "2019-03-10 제목.mp4", "date": "2019-03-10", "at": "<받은 시각>"} ]}` (지금은 빈 목록)
- **파일 이름 규칙 (반드시 지킬 것)**: `YYYY-MM-DD 제목.mp4` 예) `2019-03-10 비전설교 광야의 길.mp4`
  - 날짜 = 설교(예배) 날짜. 밴드 글 작성일과 다르면 글 제목/본문의 날짜를 우선.
  - 파일 이름에 `\ / : * ? " < > |` 금지.
- **예배 관련 영상만**: 제목/글에 설교·예배·말씀·주일·성탄·송구영신·찬양 등이 있는 것. 행사·광고·브이로그는 제외. 애매하면 사용자에게 기준을 물어볼 것.
- 폴더에는 **영상과 이 CLAUDE.md·위 두 파일 외에 아무것도 넣지 말 것** (임시 파일·로그·스크립트는 다른 곳에. 예: `%USERPROFILE%\band-downloader\`).

### 권장 구현
1. `%USERPROFILE%\band-downloader\`에 Python 또는 Node + **Playwright** 스크립트.
2. **영구 브라우저 프로필**(persistent context)로 밴드 로그인 상태 저장 → 처음 1회만 사용자가 직접 로그인(headed). 이후 headless 재사용. 로그인/비밀번호를 대신 입력하거나 저장하지 말 것.
3. 대상 밴드의 게시글(또는 동영상 모아보기)을 최신순으로 훑어 예배 영상 찾기 → `band_downloaded.json`에 없는 것만 다운로드 → 이름 변경 → 이 폴더로 이동 → 장부 기록.
   - 이미 받은 글이 연속으로 N개(예: 10개) 나오면 중단(매주 실행 시 빠르게 끝나도록). 첫 실행은 과거 전체.
   - 밴드 공식 Open API는 영상 파일 주소를 주지 않는 것으로 앎 → 브라우저 자동화가 현실적. 밴드에서 '저장'이 막혀 있으면 화면 녹화 같은 우회는 하지 말고 사용자에게 알릴 것.
4. **윈도우 작업 스케줄러**에 매주 1회 등록 (요일·시간은 사용자에게 확인 — PC가 켜져 있는 시간이어야 함). 실패 시 로그를 `band-downloader\logs\`에 남길 것.
5. 첫 실행은 사용자와 함께: 영상 1개로 시험 → 이름/위치/장부 확인 → 전체.

### 아직 사용자에게 받지 않은 정보
- 밴드 이름(또는 주소), 예배 영상이 올라오는 게시판/말머리 특징
- 밴드에서 영상 저장(다운로드) 허용 여부
- 매주 실행 요일·시간

---

## 2. 그다음 남은 일 (구글 쪽 2가지 + 연결)

1. **이 폴더 공유 설정**: 드라이브 웹에서 폴더 우클릭 → 공유 → 일반 액세스 "링크가 있는 모든 사용자 – 뷰어". (사이트가 공개라 밴드 영상도 링크 아는 사람은 볼 수 있음 — 사용자에게 이미 안내함)
2. **Google Drive API 켜기**: 유튜브 API 키(YT_API_KEY)를 만든 같은 Google Cloud 프로젝트 → API 및 서비스 → 라이브러리 → "Google Drive API" → 사용. 키에 API 제한을 걸어뒀다면 Drive API도 허용 목록에 추가.
3. **폴더 ID 연결**: 폴더 주소 `https://drive.google.com/drive/folders/<ID>`의 ID를 저장소 워크플로에 넣기.
   - `.github/workflows/youtube-sync.yml`의 `DRIVE_FOLDER_ID: ${{ vars.DRIVE_FOLDER_ID }}` 를 `DRIVE_FOLDER_ID: '<ID>'` 로 바꿔 커밋·푸시하면 됨 (폴더 ID는 비밀 아님). 또는 저장소 Settings > Secrets and variables > Actions > Variables 에 `DRIVE_FOLDER_ID` 등록.
4. 연결 후 Actions에서 **Run workflow** 1회 → 로그에서 `밴드 영상: 새 영상 N편` / `밴드 영상 추가` 확인 → 사이트에서 재생 확인.

---

## 3. 프로젝트 전체 개요

- **사이트**: https://1206aj-glitch.github.io/-/ (GitHub Pages, 저장소 `1206aj-glitch/-` 의 `index.html` 한 파일)
- **목적**: 성도가 자기 상황(상처치유·우울불안·고난시련·실패결핍·분노용서·가정가족·조급인내·나눔전도)에 맞는 설교를 찾아보게 하는 아카이브
- **채널**: 하늘스크린교회김형종목사 `UCE2gX_bg3lq1-7bn7WZAPQQ`
- ⚠️ 같은 계정의 저장소 `-.` , `-..` 는 **차량고장 분석시스템(회사 업무)** — 절대 건드리지 말 것.

### index.html 구조 (단일 파일)
- Tailwind CDN, 아이콘은 인라인 SVG(Font Awesome은 Edge 추적 방지 때문에 제거), localStorage 래퍼 `lsGet/lsSet/lsDel` (키: hs_db_v8, hs_db_ver, hs_sort, hs_deleted, hs_dark, hs_font, hs_yt_cfg)
- `masterInitialDatabase` — 2026년 txt로 넣은 기본 설교 24편 (필드: index, year, id(유튜브 ID), title, date, month, categoryKo, scripture, situation, summary, notes, timeline[{time, secs, title}])
- `/*AUTO_SERMONS_START*/var AUTO_SERMONS = [...];/*AUTO_SERMONS_END*/` — **자동화가 채우는 영역** (사람이 손으로 고치지 말 것). `mergeAutoSermons()`가 브라우저 DB에 합침: 새 것 추가, `ai_v`가 더 높으면 갱신(관리자가 직접 수정한 `edited` 항목은 유지)
- `/*YT_EMBED_START*/ ... /*YT_EMBED_END*/` — 유튜브 키/채널/DB_VERSION
- 기능: 상황 필터, 연도/월, 날짜순·역순, 다크모드, 글자 크기, 성경 구절 팝업, 성경 책갈피(66권)·성경 전체 읽기(bolls.life KRJV → get.bible 폴백), 관리자 화면(비밀번호 1234: 수정/삭제/추가/txt 일괄 등록/유튜브 동기화), 모바일 뒤로가기(history.pushState)
- 유튜브 재생: file:// 에서 embed 오류 153 → 임베드 안 함. iOS youtu.be, Android intent://(유튜브 앱), PC 새 탭. 타임라인 클릭 = 해당 초부터.
- **밴드 영상(드라이브)**: 항목에 `drive: <드라이브 파일ID>`, `id: "drive_<ID>"`, `source: "band"`. 재생은 페이지 안 iframe `https://drive.google.com/file/d/<ID>/preview`, 썸네일 `drive.google.com/thumbnail?id=<ID>`. 타임라인 바로 이동은 안 될 수 있어 안내 토스트 표시.
- 인사이트 노트: notes 문자열 `💡 주요 키워드: #a #b\n💡 원어 강해: ...\n💡 실천 지침: ...` → `renderNotesBadges()`가 태그/라벨로 표시

### 자동화 (GitHub Actions) — `.github/workflows/youtube-sync.yml`
- **매시간 :41** 실행 + 수동 Run workflow. `concurrency`로 동시 실행 방지. timeout 150분.
- Secrets: `YT_API_KEY`(YouTube Data API v3 + Drive API 용), `GEMINI_API_KEY`(Google AI Studio, **무료 등급** — 사용자의 Google AI Pro 구독은 API 한도에 반영 안 됨)
- 환경값: `AI_MAX_PER_RUN 6`, `CHANNEL_ID`, `SERMON_KEYWORD '설교|예배|말씀|주일|성탄|송구영신'`, `BACKFILL 'on'`, `BACKFILL_FROM_YEAR '2017'`, `DRIVE_FOLDER_ID`
- 남은 일이 있으면 `gh workflow run`으로 **다음 회차를 스스로 실행**(more=true). Gemini 서버 혼잡이면 **20분 뒤 재실행**(busy=true).
- 커밋 메시지 "유튜브 새 설교 자동 추가 / AI 정리" (index.html + scripts/*.json 상태 파일)

### scripts/
- `sync_youtube.py` — 메인. 순서: ① 채널 새 영상 추가(최신 설교보다 이전 날짜는 추가 안 함) ② `ai_enrich.enrich()` 올해 미정리 설교 AI 정리(**항상 최신순 — 월요일엔 전날 주일 설교가 먼저**) ③ `drive_ingest.ingest()` 밴드 영상(회당 최대 2편) ④ `backfill()` 지난 유튜브 설교를 2025→2024→…→2017 순으로 (AI 정리 성공한 것만 추가, 같은 날짜 설교가 있으면 재업로드로 보고 제외)
- `ai_enrich.py` — Gemini 호출. 유튜브 URL을 `file_data.file_uri`로 직접 전달(fps 0.2, 저해상도로 토큰 절약). 파일은 `upload_file()`(File API resumable 업로드 → ACTIVE 대기) 후 같은 방식.
  - **모델 돌려쓰기**: API에서 목록 자동 조회 → Flash 계열(최신순) → Pro 계열. **Flash-Lite는 사용자 요청으로 제외** (다시 넣지 말 것).
  - 무료 한도는 **모델별 하루 요청 수(약 20회)**, 실패한 요청도 차감. 503 혼잡은 모델당 2회만 시도 후 다음 모델, 하루 한도 소진(429 PerDay)은 그 모델 제외. 모든 모델 소진 시 그날은 요청 생략.
  - 한도일 = 미국 태평양 시간 날짜(한국 오후 4~5시 초기화).
  - 403 권한 오류 영상(생방송 직후 처리 중 등)은 그날 재시도 안 함, 다음 날 다시. 7일 연속이면 포기.
  - `AI_VERSION = 2` (인사이트 노트 추가 버전). 형식을 바꾸면 올려서 재정리.
  - 프롬프트 출력 JSON: summary, keywords, scripture("책 N장 N~N절"), timeline 8~14개, insights 3~4개(원어 강해/예화/특송/시 낭송/실천 지침/핵심 메시지 — 실천 지침 필수), situation, category
- `drive_ingest.py` — 드라이브 폴더(공개 링크) 목록을 API 키로 읽고, 새 영상 다운로드 → Gemini 업로드 → 정리 → 추가 → Gemini 파일 삭제. 파일 이름에서 날짜/제목 파싱(`2019-03-10`, `2019.3.10`, `2019년 3월 10일`, `20190310` 지원, 없으면 드라이브 업로드 날짜). **같은 날짜 설교가 유튜브 채널(또는 사이트)에 있으면 건너뜀**(유튜브 우선).
- 상태 파일: `ai_state.json`(한도일·소진 모델), `backfill_skip.json`(제외된 유튜브 ID), `drive_skip.json`(제외된 드라이브 파일 ID)

---

## 4. 현재 진행 상황 (2026-11-05 새벽)

- 사이트 자동 등록 설교 31편: 2026년 21편 전부 AI 정리 완료, 2025년 10편(2025-11-02까지 거슬러 올라옴). 기본 24편 별도.
- 지난 설교 후보 약 400편(→2017) 남음. 하루 10~15편 예상 → 약 한 달.
- 2025-12-21 「후회없는 삶」은 AI 응답 JSON 깨짐으로 한 번 실패 → 자동 재시도됨.
- 밴드: 폴더만 생성. 다운로드 자동화·공유 설정·Drive API·폴더 ID 연결 모두 미완료.

## 5. 점검 방법
- 실행 기록: https://github.com/1206aj-glitch/-/actions (워크플로 "유튜브 새 설교 자동 업데이트")
- 익명으로도 조회 가능: `curl -s "https://api.github.com/repos/1206aj-glitch/-/actions/workflows/youtube-sync.yml/runs?per_page=5"` → 각 run의 jobs → `/actions/jobs/<id>/logs`
- 로그 핵심 문구: `AI 정리 완료`, `지난 설교 추가`, `밴드 영상 추가`, `서버 혼잡`, `오늘 무료 한도`
- 진행률: index.html의 AUTO_SERMONS에서 `ai_v >= 2` 개수, 연도별 개수

## 6. 지켜온 원칙
- 빈 설교(요약·타임라인 없음)는 사이트에 올리지 않는다.
- 최신 설교 먼저, 그다음 과거로.
- 한도 낭비 금지(재시도 최소화). 실패는 다음 회차가 이어받게.
- 코드 수정 후 `python -m py_compile scripts/*.py`, index.html 스크립트는 `node --check`로 문법 확인, 가짜 응답으로 시험 후 푸시.
- 커밋은 main에 바로(사용자 저장소, 사용자가 요청한 방식).
