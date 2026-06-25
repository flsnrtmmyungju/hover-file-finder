# Hover File Finder

마우스를 텍스트 위에 올리면 로컬 폴더에서 유사한 파일을 찾아 표시하는 도구.  
Flask 로컬 서버 + 크롬 익스텐션 구성.

## 구조

```
server.py          # Flask 서버 (파일 검색·정리·변환)
compound_words.py  # 복합어·고유명사 사전
config.json        # 설정 파일
requirements.txt   # pip 의존성
extension/         # 크롬 익스텐션
```

## 설치

```bash
pip install -r requirements.txt
```

크롬 `chrome://extensions` → 개발자 모드 → `extension/` 폴더 로드

## 실행

```bash
python server.py
```

기본 포트: `7823`

## 설정 (config.json)

| 키 | 설명 |
|---|---|
| `downloads_dir` | 파일을 검색할 기본 폴더 경로 |
| `archive_folder` | 정리된 파일을 보관하는 하위 폴더명 |
| `allowed_origins` | 익스텐션 접근을 허용할 사이트 URL 패턴 |
| `port` | 서버 포트 (기본 7823) |
| `max_results` | 검색 결과 최대 개수 |

## 주요 기능

- **파일 검색**: 호버한 텍스트와 유사한 파일명 검색 (한글 띄어쓰기 무관 매칭)
- **파일명 정리**: 한글 띄어쓰기 교정, 화수 정규화 (`/rename`)
- **중복 탐지**: 동일 파일 스캔 및 삭제 (`/deduplicate-scan`)
- **파일 정리**: 다운로드 → archive 폴더 이동 (`/organize`)
- **epub 변환**: txt → epub 일괄 변환 (`/epub-batch-convert`)
