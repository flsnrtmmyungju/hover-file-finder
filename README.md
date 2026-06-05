# hover-file-finder

웹페이지에서 텍스트를 **우클릭**하면, 로컬 다운로드 폴더에서 유사한 파일을 찾아 팝업으로 보여주는 도구입니다.

Chrome 확장 프로그램 + 로컬 서버 구조로 동작합니다.

---

## 설치 방법 선택

| 방법 | 장점 | 단점 |
|---|---|---|
| **EXE (권장)** | WSL/Python 불필요, 더블클릭 실행 | 한글 띄어쓰기 교정 없음 |
| **WSL 서버** | 한글 띄어쓰기 교정 포함 전체 기능 | WSL + Python 설치 필요 |

---

## 방법 A: EXE로 실행 (간단)

### 1. 다운로드

**[Releases 페이지](https://github.com/flsnrtmmyungju/hover-file-finder/releases)** 에서 최신 버전 다운로드:
- `HoverFileFinder.exe` — 서버 + 설정 UI
- `extension.zip` — Chrome 확장 프로그램

### 2. EXE 실행 및 설정

1. `HoverFileFinder.exe`를 원하는 폴더에 저장 후 실행
2. Windows SmartScreen 경고 → **추가 정보 → 실행** 클릭
3. 설정 창에서:
   - **다운로드 폴더**: `📁 선택` 버튼으로 다운로드 폴더 지정
   - **Archive 폴더명**: 파일이동 시 생성할 하위 폴더명 (예: `정리`)
   - **허용 사이트 URL**: 사용할 사이트 URL 입력 (예: `https://mysite*.com`)
4. **저장** 클릭

> EXE 실행 후 같은 폴더에 `config.json`이 자동 생성됩니다.

### 3. Chrome 확장 프로그램 설치

1. `extension.zip` 압축 해제 → `extension` 폴더 생성
2. Chrome: `chrome://extensions` 접속
3. 우측 상단 **개발자 모드** 활성화
4. **압축해제된 확장 프로그램을 로드합니다** 클릭
5. `extension` 폴더 선택

### 4. 사용

- 사이트에서 파일명 텍스트 **우클릭** → 팝업 표시
- 팝업 **바깥 좌클릭** 또는 **✕ 버튼** 으로 닫기

---

## 방법 B: WSL 서버로 실행 (전체 기능)

한글 띄어쓰기 자동 교정(kiwipiepy) 포함. 이름정리 기능이 더 정교합니다.

### 0. 사전 준비

**WSL2 설치** — PowerShell 관리자 권한으로:
```powershell
wsl --install
```
설치 후 재시작. Ubuntu가 기본 설치됩니다.

**Python3 확인** (WSL 터미널):
```bash
python3 --version   # 3.10 이상
# 없으면:
sudo apt update && sudo apt install python3 python3-pip -y
```

### 1. 레포 클론

```bash
cd ~
git clone https://github.com/flsnrtmmyungju/hover-file-finder.git
cd hover-file-finder
```

### 2. 패키지 설치

```bash
pip3 install -r requirements.txt
pip3 install kiwipiepy   # 한글 띄어쓰기 교정 (권장)
```

### 3. config.json 생성

```bash
cp config.example.json config.json
```

`config.json` 편집:

```json
{
  "downloads_dir": "C:\\Users\\본인계정\\Downloads",
  "archive_folder": "정리",
  "allowed_origins": ["https://사용할사이트*.com"],
  "port": 7823,
  "max_results": 10,
  "min_word_length": 2
}
```

> `C:\...` Windows 경로를 그대로 쓰면 WSL이 자동으로 `/mnt/c/...`로 변환합니다.

### 4. 서버 실행

```bash
cd ~/hover-file-finder
python3 server.py
```

### 5. Chrome 확장 프로그램 설치

```bash
# extension 폴더를 Windows로 복사
cp -r ~/hover-file-finder/extension /mnt/c/Users/본인계정/Documents/extension
```

Chrome: `chrome://extensions` → 개발자 모드 → `C:\Users\본인계정\Documents\extension` 폴더 로드

---

## 팝업 기능

| 기능 | 설명 |
|---|---|
| 파일 목록 | 초록 배경 = 정확 일치 / 흰색 = 부분 일치 |
| **이름정리** (하늘색) | 다운로드 폴더 전체 파일명 일괄 정리 |
| **파일이동** (보라색) | .txt/.epub 파일을 archive 폴더로 이동 |
| **중복삭제** (빨간색) | 중복 파일 확인 후 순차 삭제 |
| **✏ 버튼** | 파일명 인라인 수정 |
| **🗑 버튼** | 파일 삭제 (확인 후) |
| 우클릭 | 검색 팝업 열기 |
| 좌클릭 / ✕ / ESC | 팝업 닫기 |

---

## 이름정리 규칙

파일명 정리 시 자동으로 적용되는 변환:

| 변환 | 예시 |
|---|---|
| 한자 → 한글 | 完→완, 完結→완, 未完→미완, 外傳→외 |
| 연재중/연재 → 미완 | `연재중` → `미완` |
| 후기 → 후, 포함 삭제 | `후기포함` → `후` |
| 외전 → 외 | `외전` → `외` |
| 본편 → 본 | `본편` → `본` |
| 숫자+편 삭제 | `183편` → `` |
| 및 → , | `A 및 B` → `A , B` |
| 불필요 태그 제거 | `@작가명`, `ⓒ저작권`, `[텍스트]` 삭제 |
| 빈 괄호 제거 | `()`, `[]` 삭제 |
| 끝 완/미완 공백 | `1-200완` → `1-200 완` |
| 특수공백 정규화 | `\xa0`, `​` → 일반 공백 |
| 복합어 결합 | `흑 기사` → `흑기사`, `돌 싱` → `돌싱` |
| 한글 띄어쓰기 교정 | `아포칼립스에집을숨김` → `아포칼립스에 집을 숨김` (**WSL 전용**) |

---

## config.json 설정값

| 키 | 설명 |
|---|---|
| `downloads_dir` | 검색할 다운로드 폴더 경로 |
| `archive_folder` | 파일이동 시 생성할 하위 폴더명 |
| `allowed_origins` | 서버 접근을 허용할 사이트 URL (`*` 와일드카드 지원) |
| `port` | 서버 포트 (기본: 7823) |
| `max_results` | 검색 결과 최대 개수 |
| `min_word_length` | 검색 최소 단어 길이 |

> **보안**: `allowed_origins`를 설정하지 않으면 모든 사이트의 요청을 수락합니다. 반드시 사용하는 사이트만 등록하세요.

---

## 트러블슈팅

**팝업이 안 뜨는 경우**
- `http://localhost:7823/status` 접속 → 서버 실행 확인
- `config.json`의 `allowed_origins`에 현재 사이트 URL 포함 여부 확인
- `chrome://extensions` → File Hover Finder 새로고침(↺) → 페이지 F5

**WSL 서버 포트 충돌**
```bash
kill -9 $(lsof -t -i:7823) && python3 server.py
```

**extension 수정 후 적용 (WSL)**
```bash
cp ~/hover-file-finder/extension/content.js /mnt/c/Users/본인계정/Documents/extension/content.js
```
→ `chrome://extensions` 새로고침(↺)

---

## 동작 환경

- **OS**: Windows (EXE) / Windows + WSL2 (서버)
- **브라우저**: Chrome / Edge (Chromium 기반)
- **Python**: 3.10+ (WSL 서버 방식만 필요)
