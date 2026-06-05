# hover-file-finder

웹페이지에서 텍스트 위에 마우스를 올리면, 로컬 다운로드 폴더에서 유사한 파일을 찾아 팝업으로 보여주는 도구입니다.

Chrome 확장 프로그램 + Python 로컬 서버 구조로 동작합니다.

---

## 파일 구조

```
hover-file-finder/
├── server.py                    # Python 로컬 서버 (핵심 로직)
├── config.json                  # 실제 설정 파일 (git 제외, 로컬 전용)
├── config.example.json          # 설정 파일 템플릿 (git 관리)
├── requirements.txt             # Python 패키지 목록
├── extension/
│   ├── manifest.json            # Chrome 확장 프로그램 설정
│   ├── content.js               # 확장 프로그램 동작 스크립트
│   ├── site.example.js          # 사이트 패턴 설정 템플릿 (git 관리)
│   └── site.js                  # 실제 사이트 패턴 설정 (git 제외, 로컬 전용)
└── spacing_cache.json           # 띄어쓰기 교정 캐시 (자동 생성, git 제외)
```

---

## 각 파일 설명

### `server.py`

Flask 기반 로컬 HTTP 서버. `http://localhost:7823` 에서 실행됩니다.

**주요 엔드포인트:**

| 엔드포인트 | 메서드 | 설명 |
|---|---|---|
| `/search` | GET | 텍스트로 다운로드 폴더에서 파일 검색 |
| `/rename` | GET/POST | 이름정리 - 전체 파일명 일괄 정리 |
| `/rename-file` | GET/POST | 특정 파일 이름 변경 |
| `/organize` | POST | .txt/.epub 파일을 archive 폴더로 이동 |
| `/delete` | GET/POST | 파일명으로 파일 삭제 |
| `/delete-path` | GET/POST | 절대 경로로 파일 삭제 |
| `/deduplicate-scan` | GET/POST | 다운로드 폴더와 archive 폴더 중복 파일 스캔 |
| `/deduplicate` | GET/POST | 중복 파일 자동 삭제 |
| `/status` | GET | 서버 상태 및 다운로드 폴더 정보 확인 |

**주요 함수:**

- `clean_name(stem)` — 파일명 정리 함수. 한자 변환, 괄호 제거, 불필요한 태그 삭제, 띄어쓰기 교정 등을 수행합니다.
- `score_filename(query_words, filename)` — 검색어와 파일명의 유사도 점수 계산
- `fix_spacing(text)` — kiwipiepy를 이용한 한글 띄어쓰기 교정 (4자 이상 붙은 한글에만 적용)
- `join_single_syllables(text)` — 글자 사이 공백이 있는 경우 합치기

---

### `config.json` (로컬 전용, git 미포함)

개인 경로 및 설정을 담는 파일입니다. **`.gitignore`에 포함되어 git에 올라가지 않습니다.**

`config.example.json`을 복사하여 생성하고 값을 수정하세요.

```bash
cp config.example.json config.json
```

```json
{
  "downloads_dir": "C:\\Users\\본인계정\\Downloads",
  "archive_folder": "archive",
  "port": 7823,
  "max_results": 10,
  "min_word_length": 2
}
```

| 키 | 설명 |
|---|---|
| `downloads_dir` | 검색할 다운로드 폴더 경로 (Windows 경로 사용) |
| `archive_folder` | 파일이동 시 이동할 하위 폴더명 |
| `port` | 서버 포트 번호 (기본값: 7823) |
| `max_results` | 검색 결과 최대 개수 |
| `min_word_length` | 검색에 사용할 최소 단어 길이 |

### `config.example.json`

`config.json`의 템플릿 파일입니다. 실제 경로나 개인정보 없이 구조만 포함되어 git으로 관리됩니다.

---

### `requirements.txt`

필요한 Python 패키지 목록입니다.

```
flask>=3.0.0
flask-cors>=4.0.0
```

선택 패키지 (한글 띄어쓰기 교정):
```bash
pip3 install kiwipiepy
```

---

### `extension/site.js` (로컬 전용, git 미포함)

활성화할 사이트의 도메인 패턴을 정의합니다. **이 파일은 `.gitignore`에 포함되어 git에 올라가지 않습니다.**

`site.example.js`를 복사하여 생성하고, 패턴을 자신의 사이트에 맞게 수정하세요.

```bash
cp extension/site.example.js extension/site.js
```

```js
const SITE_PATTERN = /^yoursite\.com$/;
```

---

### `extension/manifest.json`

Chrome 확장 프로그램의 메타정보 및 권한 설정 파일입니다.

- `host_permissions`: localhost:7823 접근 허용
- `content_scripts`: `site.js`의 `SITE_PATTERN`으로 활성화 여부 필터링

---

### `extension/content.js`

웹페이지에 삽입되어 실행되는 스크립트입니다.

**주요 동작:**

1. `site.js`의 `SITE_PATTERN`에 매칭되는 도메인에서만 활성화
2. 마우스가 텍스트 위에 올라가면 400ms 후 서버에 검색 요청
3. 결과를 마우스 커서 아래 팝업으로 표시
4. 팝업 내 기능:
   - **이름정리** (하늘색): 다운로드 폴더 전체 파일명 일괄 정리
   - **파일이동** (보라색): .txt/.epub 파일을 archive 폴더로 이동
   - **중복삭제** (빨간색): 중복 파일을 확인 후 순차 삭제
   - **파일명 옆 ✏ 버튼**: 파일명 인라인 수정
   - **파일명 옆 🗑 버튼**: 파일 삭제 (확인 후)
   - **✕ 버튼 / ESC**: 팝업 닫기

**검색 로직:**
- 정확 일치 (초록 배경): 모든 검색어 단어가 파일명에 포함된 경우
- 부분 일치: 일부 단어 또는 부분 문자열이 일치하는 경우
- 점수 높은 순 정렬

---

## 새 PC 세팅 방법 (처음부터 설치)

### 0. 사전 준비

**WSL2 설치** (Windows에서 Linux 환경 구성)

PowerShell을 관리자 권한으로 실행 후:
```powershell
wsl --install
```
설치 후 재시작. Ubuntu가 기본으로 설치됩니다.

**Python3 설치 확인** (WSL 터미널에서)
```bash
python3 --version   # 3.10 이상이어야 함
```

없으면 설치:
```bash
sudo apt update && sudo apt install python3 python3-pip -y
```

---

### 1. 레포 클론

WSL 터미널을 열고:
```bash
cd ~
git clone https://github.com/flsnrtmmyungju/hover-file-finder.git
cd hover-file-finder
```

---

### 2. Python 패키지 설치

```bash
pip3 install -r requirements.txt
pip3 install kiwipiepy   # 한글 띄어쓰기 교정 (선택사항, 권장)
```

---

### 3. `config.json` 생성

```bash
cp config.example.json config.json
```

`config.json`을 열어 **본인 Windows 계정명**과 **archive 폴더명**을 입력하세요.

```json
{
  "downloads_dir": "C:\\Users\\본인계정\\Downloads",
  "archive_folder": "원하는폴더명",
  "port": 7823,
  "max_results": 10,
  "min_word_length": 2
}
```

> WSL에서는 `C:\Users\...` Windows 경로를 그대로 써도 자동으로 `/mnt/c/...`로 변환됩니다.

---

### 4. 사이트 패턴 설정

```bash
cp extension/site.example.js extension/site.js
```

`extension/site.js`를 열어 사용할 사이트 도메인 패턴으로 수정하세요.

```js
// 예: 특정 사이트에서만 동작하도록 설정
const SITE_PATTERN = /^yoursite\.com$/;
```

정규식 패턴 예시:
- 단일 도메인: `/^example\.com$/`
- 숫자 포함: `/^site\d+\.com$/`  → `site1.com`, `site23.com` 등 매칭
- 서브도메인 포함: `/^(.+\.)?example\.com$/`

---

### 5. 서버 실행

```bash
cd ~/hover-file-finder
python3 server.py
```

정상 실행 시 아래 메시지가 출력됩니다:
```
서버 시작: http://localhost:7823
다운로드 폴더: /mnt/c/Users/...
 * Running on http://127.0.0.1:7823
```

> 서버는 Chrome 확장 프로그램이 동작할 때마다 실행되어 있어야 합니다.  
> 터미널을 닫으면 서버도 종료됩니다.

---

### 6. Chrome 확장 프로그램 설치

**extension 폴더를 Windows에서 접근 가능한 위치로 복사:**

WSL 터미널에서:
```bash
cp -r ~/hover-file-finder/extension /mnt/c/Users/본인계정/Documents/extension
```

**Chrome에서 설치:**

1. Chrome 주소창에 `chrome://extensions` 입력
2. 우측 상단 **개발자 모드** 토글 활성화
3. **압축해제된 확장 프로그램을 로드합니다** 클릭
4. 파일 탐색기에서 `C:\Users\본인계정\Documents\extension` 폴더 선택
5. **File Hover Finder** 확장이 목록에 나타나면 완료

---

### 7. 동작 확인

1. `python3 server.py` 서버가 실행 중인지 확인
2. 브라우저에서 `http://localhost:7823/status` 접속 → JSON 응답이 오면 정상
3. `site.js`에 설정한 도메인 사이트 접속
4. 텍스트 위에 마우스를 올리면 팝업이 뜨는지 확인

---

### 트러블슈팅

**서버 포트 충돌 오류**
```bash
kill -9 $(lsof -t -i:7823) && python3 server.py
```

**팝업이 안 뜨는 경우**
- `chrome://extensions` → File Hover Finder 새로고침(↺) 후 페이지 F5
- 서버가 실행 중인지 확인: `http://localhost:7823/status`
- `site.js`의 SITE_PATTERN이 현재 사이트 도메인과 일치하는지 확인

**extension 폴더 수정 후 적용**
```bash
# 수정된 파일을 Windows Documents로 재복사
cp ~/hover-file-finder/extension/content.js /mnt/c/Users/본인계정/Documents/extension/content.js
```
그 후 `chrome://extensions` → 새로고침(↺)

---

## 동작 환경

- **OS**: Windows + WSL2 (Ubuntu)
- **브라우저**: Chrome / Edge (Chromium 기반)
- **Python**: 3.10+
- **서버**: WSL에서 실행
