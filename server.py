import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from flask import Flask, request, jsonify
    from flask_cors import CORS
except ImportError:
    print("pip install flask flask-cors")
    sys.exit(1)

def send2trash(path):
    result = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True)
    win_path = result.stdout.strip().replace("'", "''")
    subprocess.run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        f"Add-Type -AssemblyName Microsoft.VisualBasic; "
        f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('{win_path}', 'OnlyErrorDialogs', 'SendToRecycleBin')"
    ], check=True)

app = Flask(__name__)

# PyInstaller 번들 경로를 sys.path에 추가
if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)

# EXE로 실행 시 실행파일 옆 경로 사용, 스크립트 실행 시 파일 옆 경로 사용
_BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
CONFIG_PATH = _BASE_DIR / "config.json"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


# config의 allowed_origins 패턴으로 CORS 허용 (* 와일드카드 → 정규식 변환)
try:
    _patterns = load_config().get("allowed_origins", [])
    if _patterns:
        def _to_regex(p):
            return "^" + re.escape(p).replace(r"\*", ".*") + "$"
        CORS(app, origins=[_to_regex(p) for p in _patterns])
    else:
        CORS(app, origins=["http://localhost:7823"])
except Exception:
    CORS(app, origins=["http://localhost:7823"])


def resolve_downloads_dir(raw_path):
    # EXE(Windows)에서는 경로 그대로 사용
    if getattr(sys, 'frozen', False):
        return raw_path
    # WSL 개발 환경: Windows 경로 → /mnt/c/... 변환
    if raw_path and len(raw_path) >= 2 and raw_path[1] == ":":
        drive = raw_path[0].lower()
        rest = raw_path[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return raw_path


import time as _time
import json as _json
import hashlib as _hashlib

from compound_words import COMPOUND_WORDS as _CW_FOR_HASH
_COMPOUND_HASH = _hashlib.md5(str(_CW_FOR_HASH).encode()).hexdigest()[:8]

_spacing_cache = {}
_cache_path = _BASE_DIR / "spacing_cache.json"
if _cache_path.exists():
    try:
        with open(_cache_path, encoding="utf-8") as _f:
            _loaded = _json.load(_f)
        if _loaded.get("__compound_hash__") == _COMPOUND_HASH:
            _spacing_cache = {k: v for k, v in _loaded.items() if k != "__compound_hash__"}
        else:
            print(f"[캐시] 복합어 목록 변경 감지 → 캐시 초기화", flush=True)
    except Exception:
        pass

def _save_cache():
    try:
        data = dict(_spacing_cache)
        data["__compound_hash__"] = _COMPOUND_HASH
        with open(_cache_path, "w", encoding="utf-8") as _f:
            _json.dump(data, _f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ── 파일 목록 캐시 ───────────────────────────────────────────────
_file_cache = {"ts": 0.0, "dir": "", "files": [], "paths": {}, "clean_stems": {}}
_FILE_CACHE_TTL = 60  # seconds

def _get_file_list(downloads_dir):
    now = _time.time()
    if now - _file_cache["ts"] < _FILE_CACHE_TTL and _file_cache["dir"] == downloads_dir:
        return _file_cache["files"], _file_cache["paths"]
    files, paths = [], {}
    try:
        for root, _, fnames in os.walk(downloads_dir):
            for f in fnames:
                files.append(f)
                if f not in paths:
                    paths[f] = os.path.join(root, f)
    except (FileNotFoundError, PermissionError):
        pass
    _file_cache.update({"ts": now, "dir": downloads_dir, "files": files, "paths": paths, "clean_stems": {}})
    return files, paths

def _invalidate_file_cache():
    _file_cache["ts"] = 0.0

def _warm_file_cache(downloads_dir):
    import threading
    def _warm():
        files, _ = _get_file_list(downloads_dir)
        clean_stems = {}
        for f in files:
            try:
                clean_stems[f] = clean_name(Path(f).stem, skip_spacing=True)
            except Exception:
                clean_stems[f] = Path(f).stem
        _file_cache["clean_stems"] = clean_stems
        _save_cache()
    threading.Thread(target=_warm, daemon=True).start()

# ── 띄어쓰기 예외 복합어 목록 ─────────────────────────────────────
# Kiwi가 분리하면 안 되는 단어들. 필요 시 자유롭게 추가하세요.
from compound_words import COMPOUND_WORDS

def _apply_rules(s):
    """Kiwi 없이도 동작하는 공통 후처리 규칙"""
    # 복합어 재결합
    for word in COMPOUND_WORDS:
        if word not in s:
            for i in range(1, len(word)):
                pat = re.escape(word[:i]) + r"\s+" + re.escape(word[i:])
                if re.search(pat, s):
                    s = re.sub(pat, word, s)
                    break
    s = re.sub(r"([A-Za-z0-9가-힣])\s+급(?![가-힣])", r"\1급", s)
    s = re.sub(r"(\S)\s+%", r"\1%", s)
    s = re.sub(r"(?<![가-힣])(\d+)\s+([가-힣])", r"\1\2", s)
    s = re.sub(r"(\d+회)\s+차(?![가-힣])", r"\1차", s)
    s = re.sub(r"미\s+완", "미완", s)
    s = re.sub(r"(?<!\s)미완$", " 미완", s)
    s = re.sub(r"(?<!\s)(?<!미)완$", " 완", s)
    return s

# EXE 환경에서는 Kiwi 로딩 생략
if getattr(sys, 'frozen', False):
    def fix_spacing(text):
        return _apply_rules(text)
else:
    try:
        from kiwipiepy import Kiwi as _Kiwi
        _kiwi = _Kiwi()

        def fix_spacing(text):
            s = _apply_rules(text)
            if re.search(r"[가-힣]{4,}", s):
                if s not in _spacing_cache:
                    _spacing_cache[s] = _kiwi.space(s)
                spaced = _spacing_cache[s]
                for word in COMPOUND_WORDS:
                    if word in s and word not in spaced:
                        for i in range(1, len(word)):
                            pat = re.escape(word[:i]) + r"\s+" + re.escape(word[i:])
                            spaced = re.sub(pat, word, spaced)
                s = spaced
                s = _apply_rules(s)
            return s

    except Exception:
        def fix_spacing(text):
            return _apply_rules(text)




EXT_STOPWORDS = {"txt", "pdf", "doc", "docx", "zip", "rar", "alz", "hwp",
                 "xlsx", "pptx", "mp3", "mp4", "jpg", "png", "gif", "exe",
                 "mb", "kb", "gb", "tb", "pb"}

def strip_episode(text):
    """숫자-숫자(화수 패턴)부터 뒷부분 제거 → 순수 제목만 추출"""
    return re.sub(r'\s*\d+[-~]\d+.*$', '', text).strip()


def join_single_syllables(text):
    """한글이 한 글자씩 공백으로 분리된 경우 합치기"""
    parts = text.split(" ")
    korean_parts = [p for p in parts if re.match(r"^[가-힣]+$", p)]
    if korean_parts and all(len(p) == 1 for p in korean_parts):
        return re.sub(r"(?<=[가-힣]) (?=[가-힣])", "", text)
    return text


def score_filename(query_words, filename):
    # 화수 패턴 이후 제거 후 순수 제목으로만 비교
    name_no_ext = join_single_syllables(strip_episode(Path(filename).stem.lower()))
    file_words = {
        w for w in re.findall(r"[가-힣a-z]+", name_no_ext)
        if len(w) >= 2 and w not in EXT_STOPWORDS
    }

    # 정확 일치
    common = query_words & file_words
    score = len(common)

    # 부분 포함: "해골"이 "해골병사로" 안에 있는 경우 등
    unmatched = query_words - common
    for qw in unmatched:
        if len(qw) < 2:
            continue
        for fw in file_words:
            if qw in fw or fw in qw:
                score += 0.7
                break

    if score > 0:
        return score / max(len(query_words), len(file_words), 1)

    for word in query_words:
        if len(word) >= 4 and word in name_no_ext:
            return 0.15
    return 0.0


HANJA_COMPLETE  = "完結"  # 完結
HANJA_UNFINISH  = "未完"  # 未完
HANJA_UNFINISH1 = "未"        # 未
HANJA_SIDE      = "外傳"  # 外傳
HANJA_SIDE2     = "外전"  # 外전 (한자+한글)
HANJA_SIDE3     = "外"        # 外 단독
HANJA_C         = "完"        # 完
HANJA_AFTER     = "後"        # 後 (후기/에필)


def clean_name(stem, skip_spacing=False):
    # 특수 공백 문자 → 일반 공백
    s = stem.replace('\xa0', ' ').replace('​', '').replace('　', ' ')
    # 끝 날짜태그 제거 (예: -현판TS260322, -로 260321, -현ts260306)
    s = re.sub(r'[-]\s*[가-힣]{1,3}[a-zA-Z]{0,2}\s?\d{6}\s*$', '', s)
    # 2단계: 파일명 앞 [텍스트] 처리 (괄호 제거 전에 먼저)
    m = re.match(r"^\s*\[(완결|완)\]\s*(?:완결|완)?\s*", s)
    if m:
        rest = s[m.end():].strip()
        s = rest if re.search(r"\s완$", rest) else rest + " 완"
    else:
        s = re.sub(r"^\s*\[[^\]]*\]\s*", "", s)

    # 3단계: 인라인 괄호 처리 (괄호 제거 전에 먼저) — 한글/한자 마커 모두
    s = re.sub(r"[\(\[]\s*완결\s*[\)\]]", " 완 ", s)
    s = re.sub(r"[\(\[]\s*완\s*[\)\]]",   " 완 ", s)
    s = re.sub(r"[\(\[]\s*미완\s*[\)\]]", " 미완 ", s)
    # 한자 마커 괄호 → 한글 (독음 삭제 전에 먼저 변환)
    s = re.sub(r"[\(\[]\s*完結\s*[\)\]]", " 완 ", s)
    s = re.sub(r"[\(\[]\s*完\s*[\)\]]",   " 완 ", s)
    s = re.sub(r"[\(\[]\s*未完\s*[\)\]]", " 미완 ", s)
    s = re.sub(r"[\(\[]\s*未\s*[\)\]]",   " 미완 ", s)
    s = re.sub(r"[\(\[]\s*外傳\s*[\)\]]", " 외 ", s)
    s = re.sub(r"[\(\[]\s*外\s*[\)\]]",   " 외 ", s)
    s = re.sub(r"[\(\[]\s*後\s*[\)\]]",   " 후 ", s)

    # 한자 독음 괄호 제거 (天災) [天災] — 붙어있는 글자 분리 없이
    _HANJA = "[\u3400-\u9fff\uf900-\ufaff]"
    s = re.sub(r"\(" + _HANJA + r"+\)", "", s)
    s = re.sub(r"\[" + _HANJA + r"+\]", "", s)
    # (완-후기) (完, 에필 포함) 등 완+내용 괄호에서 완 추출 (통째 제거 전에 먼저)
    s = re.sub(r"[\(\[]\s*(?:완결|완|完結|完)\s*[-,，、]\s*([^\)\]]*?)[\)\]]", r" 완 \1 ", s)
    # 중간 [텍스트] / (텍스트) 내용째로 제거 (마커 변환 후 남은 것)
    s = re.sub(r"\s*\[[^\]]*\]", "", s)
    s = re.sub(r"\s*\([^)]*\)", "", s)
    # 괄호 문자 잔여분 제거
    s = re.sub(r"[{}()\[\]]", "", s)

    # 1단계: 한자 -> 한글 (괄호 없는 단순 치환)
    s = s.replace(HANJA_COMPLETE,  "완")
    s = s.replace(HANJA_UNFINISH,  "미완")
    s = s.replace(HANJA_SIDE,      "외")
    s = s.replace(HANJA_SIDE2,     "외")
    s = s.replace(HANJA_SIDE3,     "외")
    s = s.replace(HANJA_C,         "완")
    s = s.replace(HANJA_UNFINISH1, "미완")
    s = s.replace(HANJA_AFTER,     "후")
    # 나머지 한자 전부 삭제
    s = re.sub(r"[\u3400-\u9fff\uf900-\ufaff]+", "", s)
    # 연재중 → 미완
    s = re.sub(r"연재\s*중", " 미완 ", s)
    s = re.sub(r"연재(?!\S)", " 미완 ", s)
    s = re.sub(r"(?<![가-힣])외전(?![가-힣])", " 외 ", s)
    s = re.sub(r"(?<![가-힣])후기(?![가-힣])", " 후 ", s)
    s = re.sub(r"(?<![가-힣])포함(?![가-힣])", " ", s)
    s = s.replace("완결", "완")

    # 4단계: 기타 정리
    s = s.replace("본편", "본")                       # 본편 → 본
    s = re.sub(r"(\d+)편", r"\1", s)                  # 숫자+편 → 숫자 (183편 → 183)
    s = re.sub(r"(\d+)화", r"\1", s)                  # 숫자+화 → 숫자 (23화 → 23)
    s = re.sub(r"(?<![가-힣])및(?![가-힣])", ",", s)   # 및 → ,
    # 빈 () 제거, [텍스트] 전부 제거, (txt) 등 제거
    s = re.sub(r"\(\s*\d+\s*\)", "", s)  # (1) (2) 등 숫자만 있는 괄호
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"\(\s*txt\s*\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"19N", "", s, flags=re.IGNORECASE)
    s = re.sub(r"(?<=.)텍본", "", s)  # 맨 앞 텍본은 유지
    s = s.replace("#", "")                              # # 삭제
    s = s.replace("+", " ")
    s = s.replace("_", " ")
    s = re.sub(r"\s*ⓒ\S+(?:\s+\S+)*?(?=\s+\d|\s*$)", "", s)  # ⓒ작가명(다중단어) 제거 — _ 치환 후 실행
    s = re.sub(r"\s*@\S+", "", s)   # @작가명 제거 (어느 위치든)
    s = re.sub(r'\b20\d{2}(?:\s+\d{1,2}){2,5}', '', s)   # 타임스탬프 제거 (2025 01 12 20 25 35)
    s = s.replace("~", "-")
    s = re.sub(r"\b0+(\d+)(?=-)", r"\1", s)            # 앞자리 0 제거 (001- → 1-)
    s = re.sub(r"\b0+(?=-)", "1", s)                   # 0만 있을 경우 1로 (000- → 1-)
    s = re.sub(r"([가-힣])(\d)", r"\1 \2", s)         # 한글+숫자 사이 공백 삽입
    s = re.sub(r"(\d)완", r"\1 완", s)                         # 숫자완 → 숫자 완
    s = re.sub(r"(?<![0-9])0*1 (\d{2,}) 완", r"1-\1 완", s)    # 1 숫자 완 / 001 숫자 완 → 1-숫자 완
    s = re.sub(r"(?<![0-9-])(\d{3,4})(?!\d) 완", r"1-\1 완", s)  # 세/네자리숫자 완 → 1-N 완
    s = re.sub(r"(?<!\d)-(\d{3,4})(?!\d) 완", r"1-\1 완", s)    # -세/네자리숫자 완 → 1-N 완
    # 끝에 숫자만 있고 범위패턴(숫자-숫자)이 없으면 1-숫자로
    if not re.search(r"\d+-\d+", s):
        s = re.sub(r"\s*-(\d{2,})$", r" 1-\1", s)             # -숫자 → 1-숫자
        s = re.sub(r"(?<![0-9-])\b1\s+(\d{2,})\s*$", r"1-\1", s)  # "1 N" → "1-N" (중복 방지)
        s = re.sub(r"(?<![0-9-])(\d{2,})$", r"1-\1", s)       # 숫자 → 1-숫자
    s = re.sub(r" +", " ", s).strip()
    if not skip_spacing:
        s = fix_spacing(s)
    # 띄어쓰기 후 재처리 - 한글이 아닌 문자로 둘러싸인 단어 치환
    s = re.sub(r"(?<![가-힣])외전(?![가-힣])", " 외 ", s)
    s = re.sub(r"(?<![가-힣])후기(?![가-힣])", " 후 ", s)
    s = re.sub(r"(?<![가-힣])포함(?![가-힣])", " ", s)
    # 한글 1~2자만 남은 빈 괄호 정리
    s = re.sub(r"[\(\[]\s*[가-힣]{0,3}\s*[\)\]]", "", s)
    s = re.sub(r" +", " ", s).strip()
    s = re.sub(r"(\d)완", r"\1 완", s)                 # fix_spacing 후 숫자완 → 숫자 완 재보정
    # 어디서든 "미 완" → "미완" 최종 보정
    s = re.sub(r"미\s+완", "미완", s)
    # 끝 완/미완 앞 공백 보장 ("미완"의 완은 제외)
    s = re.sub(r"(?<!\s)미완$", " 미완", s)
    s = re.sub(r"(?<!\s)(?<!미)완$", " 완", s)
    # 범위(1-N) 이후: 완/미완/외/에필/후만 허용, 나머지 제거, 순서 정렬
    _MARKER_MAP = {
        '완': ('완', 0), '미완': ('미완', 0),
        '외': ('외', 1), '외전': ('외', 1), '번외': ('외', 1),
        '에필': ('에필', 2), '에필로그': ('에필', 2),
        '후': ('후', 3), '후기': ('후', 3),
    }
    m_range = re.search(r"(\d+-\d+권?)(.*?)$", s)
    if m_range:
        pre = s[:m_range.end(1)]
        tokens = re.split(r'[\s,]+', m_range.group(2).strip())
        _sorted_keys = sorted(_MARKER_MAP.keys(), key=len, reverse=True)
        seen = {}      # canonical → order
        seen_disp = {} # canonical → display string (외전은 회차 포함)
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            remaining = tok.lower().strip(',')
            while remaining:
                matched = False
                for key in _sorted_keys:
                    if remaining.startswith(key):
                        canonical, order = _MARKER_MAP[key]
                        if canonical not in seen:
                            seen[canonical] = order
                            # 외전 계열이면 다음 토큰이 범위인지 확인
                            if canonical == '외' and i + 1 < len(tokens):
                                nxt = tokens[i + 1].strip(',')
                                if re.match(r'^\d+[-~]\d+$|^\d+$', nxt):
                                    seen_disp[canonical] = f'외 {nxt}'
                                    i += 1
                                else:
                                    seen_disp[canonical] = '외'
                            else:
                                seen_disp[canonical] = canonical
                        remaining = remaining[len(key):].strip(',')
                        matched = True
                        break
                if not matched:
                    # N부 패턴 (1부, 2부 등) 보존
                    if re.match(r'^\d+부$', remaining):
                        if '부' not in seen:
                            seen['부'] = -1  # 완 앞에 오도록
                            seen_disp['부'] = remaining
                    break
            i += 1
        markers = [seen_disp[m] for m, _ in sorted(seen.items(), key=lambda x: x[1])]
        s = (pre + (" " + " ".join(markers) if markers else "")).strip()
    else:
        # 범위 없는 경우: 완/미완 뒤 접미사만 보존
        _KNOWN_SFX = {'외전', '번외', '에필로그', '에필', '후기', '외', '후'}
        m_end = re.search(r"(완|미완)((?:\s+\S+)*)$", s)
        if m_end:
            pre = s[:m_end.start()]
            marker = m_end.group(1)
            words = m_end.group(2).split()
            kept = []
            for w in words:
                w_clean = w.strip(',')
                if w_clean in _KNOWN_SFX:
                    kept.append(w_clean)
                else:
                    break
            s = (pre + marker + (" " + " ".join(kept) if kept else "")).strip()
    return s


@app.route("/search")
def search():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    max_results = config.get("max_results", 10)
    min_word_len = config.get("min_word_length", 2)

    import unicodedata
    query = unicodedata.normalize("NFC", request.args.get("text", "").strip())
    # 한글이 한 글자씩 공백으로 분리된 경우 합치기 ("일 검 독 존" → "일검독존")
    parts = query.split(" ")
    korean_parts = [p for p in parts if re.match(r"^[가-힣]+$", p)]
    if korean_parts and all(len(p) == 1 for p in korean_parts):
        query = re.sub(r"(?<=[가-힣]) (?=[가-힣])", "", query)
    if not query or len(query) < 2:
        return jsonify({"exact": [], "partial": []})

    all_files, file_paths = _get_file_list(downloads_dir)
    if not all_files and not os.path.isdir(downloads_dir):
        return jsonify({"error": f"폴더를 찾을 수 없음: {downloads_dir}"}), 500

    query_clean = re.sub(r"\.\w+$", "", query.strip())
    query_clean = clean_name(query_clean)
    query_clean = strip_episode(query_clean)  # 화수 패턴 이후 제거
    query_words = {
        w for w in re.findall(r"[가-힣a-z]+", query_clean.lower())
        if len(w) >= min_word_len and w not in EXT_STOPWORDS
    }
    if not query_words:
        return jsonify({"no_search": True})

    exact = []
    partial = []
    clean_stems = _file_cache.get("clean_stems", {})

    for f in all_files:
        # 원본 파일명으로 매칭
        score = score_filename(query_words, f)

        # clean_name 버전으로도 매칭 (워밍 완료 시)
        cstem = clean_stems.get(f, "")
        if cstem:
            score2 = score_filename(query_words, cstem + Path(f).suffix)
            score = max(score, score2)

        if score <= 0:
            continue

        # exact 판정: 원본 단어 OR clean 단어 중 하나라도 쿼리 단어 포함
        raw_words = {
            w for w in re.findall(r"[가-힣a-z]+", join_single_syllables(Path(f).stem.lower()))
            if len(w) >= 2 and w not in EXT_STOPWORDS
        }
        clean_words = {
            w for w in re.findall(r"[가-힣a-z]+", join_single_syllables(cstem.lower()))
            if len(w) >= 2 and w not in EXT_STOPWORDS
        } if cstem else set()

        is_exact = bool(query_words) and query_words <= (raw_words | clean_words)
        if is_exact:
            exact.append((score, f))
        else:
            partial.append((score, f))

    exact.sort(key=lambda x: (-x[0], x[1].lower()))
    partial.sort(key=lambda x: (-x[0], x[1].lower()))

    def to_item(fname):
        path = file_paths.get(fname, "")
        try:
            mb = round(os.path.getsize(path) / (1024 * 1024), 1) if path else 0
        except Exception:
            mb = 0
        return {"name": fname, "size": mb}

    return jsonify({
        "exact": [to_item(f) for _, f in exact[:max_results]],
        "partial": [to_item(f) for _, f in partial[:max_results]],
    })


@app.route("/delete", methods=["GET", "POST"])
def delete_file():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    filename = request.args.get("filename", "").strip()

    if not filename:
        return jsonify({"error": "파일명 없음"}), 400

    target = None
    for root, dirs, files in os.walk(downloads_dir):
        if filename in files:
            candidate = os.path.join(root, filename)
            if os.path.realpath(candidate).startswith(os.path.realpath(downloads_dir)):
                target = candidate
                break

    if not target or not os.path.isfile(target):
        return jsonify({"error": "파일을 찾을 수 없음"}), 404

    try:
        send2trash(target)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/rename-file", methods=["GET", "POST"])
def rename_file():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    old_name = request.args.get("old", "").strip()
    new_name = request.args.get("new", "").strip()

    if not old_name or not new_name or old_name == new_name:
        return jsonify({"error": "파일명 오류"}), 400

    # 안전 문자 검사 (경로 탈출 방지)
    if any(c in new_name for c in ["/", "\\", "..", ":"]):
        return jsonify({"error": "허용되지 않는 문자"}), 400

    import unicodedata
    old_nfc = unicodedata.normalize("NFC", old_name)
    old_nfd = unicodedata.normalize("NFD", old_name)

    target = None
    for root, dirs, files in os.walk(downloads_dir):
        for f in files:
            f_nfc = unicodedata.normalize("NFC", f)
            if f_nfc == old_nfc or unicodedata.normalize("NFD", f) == old_nfd:
                candidate = os.path.join(root, f)
                if os.path.realpath(candidate).startswith(os.path.realpath(downloads_dir)):
                    target = candidate
                    break
        if target:
            break

    if not target:
        return jsonify({"error": f"파일 없음: {old_name!r}"}), 404

    dst = os.path.join(os.path.dirname(target), new_name)
    if os.path.exists(dst):
        dup_dir = os.path.join(downloads_dir, "중복")
        os.makedirs(dup_dir, exist_ok=True)
        dup_dst = os.path.join(dup_dir, os.path.basename(target))
        try:
            shutil.move(target, dup_dst)
            return jsonify({"ok": True, "moved_to_dup": True, "new_name": os.path.basename(dup_dst)})
        except Exception as e:
            return jsonify({"error": f"중복 이동 실패: {e}"}), 500

    try:
        os.rename(target, dst)
        return jsonify({"ok": True, "new_name": new_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _do_rename(target_dir, label, recursive=True):
    renamed, skipped, errors = 0, 0, []
    if recursive:
        all_files = [(root, f) for root, _, files in os.walk(target_dir) for f in files]
    else:
        all_files = [(target_dir, f) for f in os.listdir(target_dir)
                     if os.path.isfile(os.path.join(target_dir, f))]
    total = len(all_files)
    print(f"[이름정리/{label}] 시작 - 총 {total}개 파일", flush=True)
    for processed, (root, f) in enumerate(all_files, 1):
        src = os.path.join(root, f)
        p = Path(f)
        new_stem = clean_name(p.stem)
        new_name = new_stem + p.suffix
        if new_name == f:
            skipped += 1
            continue
        dst = os.path.join(root, new_name)
        if os.path.exists(dst):
            skipped += 1
            continue
        try:
            os.rename(src, dst)
            renamed += 1
            print(f"[이름정리/{label}] ({processed}/{total}) {f!r} → {new_name!r}", flush=True)
        except Exception as e:
            errors.append(f)
        if processed % 50 == 0:
            print(f"[이름정리/{label}] 진행 중... ({processed}/{total}) 변경 {renamed}개", flush=True)
    _invalidate_file_cache()
    _save_cache()
    print(f"[이름정리/{label}] 완료 - 변경 {renamed}개 / 스킵 {skipped}개", flush=True)
    result = {"renamed": renamed, "skipped": skipped, "errors": errors}
    _warm_file_cache(target_dir)
    return result


@app.route("/rename", methods=["GET", "POST"])
def rename_novels():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    return jsonify(_do_rename(downloads_dir, "전체", recursive=True))


@app.route("/rename/downloads", methods=["GET", "POST"])
def rename_downloads():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    return jsonify(_do_rename(downloads_dir, "다운로드", recursive=False))


@app.route("/rename/archive", methods=["GET", "POST"])
def rename_archive():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    novel_dir = os.path.join(downloads_dir, config.get("archive_folder", "archive"))
    if not os.path.isdir(novel_dir):
        return jsonify({"error": "archive 폴더가 없습니다"}), 404
    return jsonify(_do_rename(novel_dir, "소설폴더", recursive=True))




@app.route("/deduplicate-scan", methods=["GET", "POST"])
def deduplicate_scan():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    novel_dir = os.path.join(downloads_dir, config.get("archive_folder", "archive"))

    if not os.path.isdir(novel_dir):
        return jsonify({"error": "archive 폴더가 없습니다"}), 404

    min_word_len = config.get("min_word_length", 2)

    def file_words(filename):
        """파일명에서 제목 단어 추출 (화수 제거, 숫자 제외)"""
        stem = strip_episode(Path(filename).stem.lower())
        return {w for w in re.findall(r"[가-힣a-z]+", stem)
                if len(w) >= min_word_len and w not in EXT_STOPWORDS}

    def title_score(words1, words2):
        """두 단어 집합 유사도 (0~1)"""
        if not words1 or not words2:
            return 0.0
        common = words1 & words2
        score = float(len(common))
        for qw in words1 - common:
            for fw in words2:
                if qw in fw or fw in qw:
                    score += 0.7
                    break
        return score / max(len(words1), len(words2), 1)

    MATCH_THRESHOLD = 0.8  # 이 점수 이상이면 중복으로 판단

    # archive 폴더 파일 수집 {파일명: {ext: path, words: set}}
    novel_files = []
    for root, dirs, files in os.walk(novel_dir):
        for f in files:
            novel_files.append({
                "name": f,
                "path": os.path.join(root, f),
                "ext":  Path(f).suffix.lower(),
                "words": file_words(f),
            })

    # 다운로드 최상위 파일 수집
    dl_files = []
    for f in os.listdir(downloads_dir):
        path = os.path.join(downloads_dir, f)
        if not os.path.isfile(path):
            continue
        dl_files.append({
            "name": f,
            "path": path,
            "ext":  Path(f).suffix.lower(),
            "words": file_words(f),
        })

    items = []
    matched_dl = set()

    for dl in dl_files:
        if not dl["words"]:
            continue
        best_score = 0.0
        best_nov = None

        for nov in novel_files:
            if not nov["words"]:
                continue
            score = title_score(dl["words"], nov["words"])
            if score > best_score:
                best_score = score
                best_nov = nov

        if best_nov is None or best_score < MATCH_THRESHOLD:
            continue

        matched_dl.add(dl["name"])

        dl_is_txt  = dl["ext"]  == ".txt"
        nov_is_txt = best_nov["ext"] == ".txt"
        dl_is_epub  = dl["ext"]  == ".epub"
        nov_is_epub = best_nov["ext"] == ".epub"

        def fsize(path):
            try: return round(os.path.getsize(path) / (1024*1024), 1)
            except: return 0

        # txt vs epub → epub 삭제
        if dl_is_epub and nov_is_txt:
            items.append({
                "delete_path": dl["path"], "keep_path": best_nov["path"],
                "delete_name": dl["name"], "keep_name": best_nov["name"],
                "delete_loc": "다운로드", "keep_loc": "archive",
                "delete_size": fsize(dl["path"]), "keep_size": fsize(best_nov["path"]),
                "reason": f"유사도 {best_score:.0%} — txt 우선 (epub 삭제)",
            })
        elif dl_is_txt and nov_is_epub:
            items.append({
                "delete_path": best_nov["path"], "keep_path": dl["path"],
                "delete_name": best_nov["name"], "keep_name": dl["name"],
                "delete_loc": "archive", "keep_loc": "다운로드",
                "delete_size": fsize(best_nov["path"]), "keep_size": fsize(dl["path"]),
                "reason": f"유사도 {best_score:.0%} — txt 우선 (epub 삭제)",
            })
        else:
            items.append({
                "delete_path": dl["path"], "keep_path": best_nov["path"],
                "delete_name": dl["name"], "keep_name": best_nov["name"],
                "delete_loc": "다운로드", "keep_loc": "archive",
                "delete_size": fsize(dl["path"]), "keep_size": fsize(best_nov["path"]),
                "reason": f"유사도 {best_score:.0%}",
            })

    return jsonify({"items": items, "total": len(items)})


@app.route("/delete-path", methods=["GET", "POST"])
def delete_path():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    path = request.args.get("path", "").strip()

    if not path:
        return jsonify({"error": "경로 없음"}), 400

    real = os.path.realpath(path)
    base = os.path.realpath(downloads_dir)
    if not real.startswith(base):
        return jsonify({"error": "허용되지 않은 경로"}), 403

    if not os.path.isfile(real):
        return jsonify({"error": "파일 없음"}), 404

    try:
        send2trash(real)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/deduplicate", methods=["GET", "POST"])
def deduplicate():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    novel_dir = os.path.join(downloads_dir, config.get("archive_folder", "archive"))

    if not os.path.isdir(novel_dir):
        return jsonify({"error": "archive 폴더가 없습니다"}), 404

    # archive 폴더 파일 수집 (하위 포함)
    novel_files = {}
    for root, dirs, files in os.walk(novel_dir):
        for f in files:
            p = Path(f)
            stem = p.stem
            ext = p.suffix.lower()
            if stem not in novel_files:
                novel_files[stem] = {}
            novel_files[stem][ext] = os.path.join(root, f)

    # 다운로드 폴더 최상위 파일만
    dl_files = {}
    for f in os.listdir(downloads_dir):
        path = os.path.join(downloads_dir, f)
        if not os.path.isfile(path):
            continue
        p = Path(f)
        dl_files[p.stem] = dl_files.get(p.stem, {})
        dl_files[p.stem][p.suffix.lower()] = path

    deleted, errors = 0, []

    def remove(path):
        nonlocal deleted
        try:
            if os.path.exists(path):
                send2trash(path)
                deleted += 1
        except Exception as e:
            errors.append(str(e))

    for stem, dl_exts in dl_files.items():
        if stem not in novel_files:
            continue
        novel_exts = novel_files[stem]

        # 완전 동일 (이름+확장자) → 다운로드 파일 삭제
        for ext in list(dl_exts.keys()):
            if ext in novel_exts:
                remove(dl_exts[ext])

        # epub ↔ txt 쌍: txt 남기고 epub 삭제
        dl_epub = ".epub" in dl_exts
        dl_txt  = ".txt"  in dl_exts
        nv_epub = ".epub" in novel_exts
        nv_txt  = ".txt"  in novel_exts

        # 다운로드에 epub, archive에 txt → 다운로드 epub 삭제
        if dl_epub and nv_txt:
            remove(dl_exts[".epub"])

        # 다운로드에 txt, archive에 epub → archive epub 삭제
        if dl_txt and nv_epub:
            remove(novel_exts[".epub"])

    return jsonify({"deleted": deleted, "errors": errors})

@app.route("/organize", methods=["POST"])
def organize():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    novel_dir = os.path.join(downloads_dir, config.get("archive_folder", "archive"))

    try:
        os.makedirs(novel_dir, exist_ok=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    ALLOWED_EXT = {".txt", ".epub"}
    moved, skipped, errors = 0, 0, []
    for f in os.listdir(downloads_dir):
        src = os.path.join(downloads_dir, f)
        if not os.path.isfile(src):
            continue
        if Path(f).suffix.lower() not in ALLOWED_EXT:
            continue
        dst = os.path.join(novel_dir, f)
        if os.path.exists(dst):
            skipped += 1
            continue
        try:
            shutil.move(src, dst)
            moved += 1
        except Exception as e:
            errors.append(f)

    if moved:
        _invalidate_file_cache()
        _warm_file_cache(downloads_dir)
    return jsonify({"moved": moved, "skipped": skipped, "errors": errors})




@app.route("/status")
def status():
    config = load_config()
    raw = config.get("downloads_dir", "")
    resolved = resolve_downloads_dir(raw)
    exists = os.path.isdir(resolved)
    return jsonify({
        "status": "ok",
        "downloads_dir_config": raw,
        "downloads_dir_resolved": resolved,
        "dir_exists": exists,
    })


@app.route("/extract", methods=["POST"])
def extract_file():
    import zipfile, unicodedata
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    filename = request.args.get("filename", "").strip()
    if not filename:
        return jsonify({"error": "파일명 없음"}), 400

    fn_nfc = unicodedata.normalize("NFC", filename)
    target = None
    for root, dirs, files in os.walk(downloads_dir):
        for f in files:
            if unicodedata.normalize("NFC", f) == fn_nfc:
                target = os.path.join(root, f)
                break
        if target:
            break

    if not target:
        return jsonify({"error": f"파일 없음: {filename}"}), 404

    stem = os.path.splitext(filename)[0]
    base_dir = os.path.dirname(target)

    try:
        import shutil
        members = []
        with zipfile.ZipFile(target, 'r') as zf:
            for info in zf.infolist():
                try:
                    name = info.filename.encode('cp437').decode('cp949')
                except Exception:
                    name = info.filename
                members.append(name)

            if len(members) == 1:
                cleaned_stem = clean_name(stem)
                extract_dir  = os.path.join(base_dir, cleaned_stem)
                os.makedirs(extract_dir, exist_ok=True)
            else:
                extract_dir = os.path.join(base_dir, stem)
                os.makedirs(extract_dir, exist_ok=True)

            for info in zf.infolist():
                try:
                    info.filename = info.filename.encode('cp437').decode('cp949')
                except Exception:
                    pass
                zf.extract(info, extract_dir)
        # with 블록 종료 → zip 파일 닫힘

        # 1개짜리: 원본이름 + 필터링된 압축파일명 복사본 + zip 이동
        if len(members) == 1:
            inner_name    = members[0]
            inner_ext     = os.path.splitext(inner_name)[1]
            original_path = os.path.join(extract_dir, inner_name)
            renamed_name  = cleaned_stem + inner_ext
            renamed_path  = os.path.join(extract_dir, renamed_name)
            if original_path != renamed_path and os.path.exists(original_path):
                shutil.copy2(original_path, renamed_path)
            zip_dst = os.path.join(extract_dir, filename)
            if target != zip_dst:
                shutil.move(target, zip_dst)
            return jsonify({"ok": True, "extracted": 1, "dir": extract_dir,
                            "original": inner_name, "renamed": renamed_name})

        return jsonify({"ok": True, "extracted": len(members), "dir": extract_dir})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/extract-all", methods=["POST"])
def extract_all():
    import zipfile, unicodedata
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))

    zips = [
        os.path.join(downloads_dir, f)
        for f in os.listdir(downloads_dir)
        if f.lower().endswith(".zip") and os.path.isfile(os.path.join(downloads_dir, f))
    ]

    def clean_stem(s):
        has_complete = bool(re.search(r'[(\[（【]?완결[)\]）】]?', s))
        s = re.sub(r'\s*[(\[（【]완결[)\]）】]\s*', ' ', s)
        s = re.sub(r'\s+완결\s*$', '', s)
        s = re.sub(r'\s+', ' ', s).strip()
        if has_complete and not re.search(r'\s완$', s):
            s = s + ' 완'
        return s

    def num_key(pair):
        nm = pair[1].lower()
        nums = [int(n) for n in re.findall(r'\d+', nm)]
        n = nums[0] if nums else 0
        if '후기' in nm: return (4, n)
        if any(k in nm for k in ('에필로그', '에필')): return (3, n)
        if any(k in nm for k in ('외전', '번외')): return (2, n)
        if any(k in nm for k in ('프롤로그', '서장')): return (0, n)
        return (1, n)

    def first_num(nm):
        m = re.search(r'\d+', nm)
        return int(m.group()) if m else None

    def range_suffix(sorted_files):
        main = [(info, nm) for info, nm in sorted_files if num_key((info, nm))[0] == 1]
        has_외전 = any(num_key(p)[0] == 2 for p in sorted_files)
        has_에필 = any(num_key(p)[0] == 3 for p in sorted_files)
        has_후기 = any(num_key(p)[0] == 4 for p in sorted_files)
        has_완 = any(any(k in p[1].lower() for k in ('완결', '완', '끝')) for p in sorted_files)

        base = main if main else sorted_files
        n0 = first_num(base[0][1])
        n1 = first_num(base[-1][1])

        if n0 is not None and n0 == 0:
            n0 = 1

        suffix = ""
        if n0 is not None:
            suffix += f" {n0}-{n1}" if (n1 is not None and n1 != n0) else f" {n0}"
        if has_완:
            suffix += " 완"
        if has_외전:
            suffix += " 외"
        if has_에필:
            suffix += " 에필"
        if has_후기:
            suffix += " 후"
        return suffix

    done, errors = [], []
    for zip_path in zips:
        zip_name = os.path.basename(zip_path)
        stem = clean_stem(os.path.splitext(zip_name)[0])
        base_dir = os.path.dirname(zip_path)
        out_folder = os.path.join(base_dir, stem)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                members = []
                for info in zf.infolist():
                    try:
                        name = info.filename.encode('cp437').decode('cp949')
                    except Exception:
                        name = info.filename
                    members.append((info, name))

                files_only = [(info, nm) for info, nm in members if not nm.endswith('/')]
                os.makedirs(out_folder, exist_ok=True)

                if len(files_only) == 1:
                    info, member_name = files_only[0]
                    member_ext = os.path.splitext(member_name)[1]
                    new_filename = stem + member_ext
                    info.filename = member_name
                    zf.extract(info, out_folder)
                    extracted = os.path.join(out_folder, member_name)
                    dst_path = os.path.join(out_folder, new_filename)
                    if extracted != dst_path and os.path.exists(extracted):
                        shutil.copy2(extracted, dst_path)
                    done.append(new_filename)
                else:
                    txt_files = [(info, nm) for info, nm in files_only if nm.lower().endswith('.txt')]
                    if txt_files:
                        txt_files.sort(key=num_key)
                        parts = []
                        for info, nm in txt_files:
                            raw = zf.read(info)
                            for enc in ('utf-8-sig', 'cp949', 'utf-8'):
                                try:
                                    content = raw.decode(enc)
                                    break
                                except Exception:
                                    continue
                            else:
                                content = raw.decode('cp949', errors='replace')
                            header = os.path.splitext(nm)[0]
                            parts.append(f"{header}\n{content}")
                        merged = "\n".join(parts)
                        out_name = stem + range_suffix(txt_files) + ".txt"
                        with open(os.path.join(out_folder, out_name), 'w', encoding='utf-8') as f:
                            f.write(merged)

                        all_names = [nm for _, nm in files_only]
                        merged_names = [nm for _, nm in txt_files]
                        log_lines = ["[원본 파일 목록]"]
                        log_lines += [f"  {nm}" for nm in all_names]
                        log_lines += ["", "[합친 순서]"]
                        log_lines += [f"  {i+1}. {os.path.splitext(nm)[0]}" for i, nm in enumerate(merged_names)]
                        log_lines += ["", f"→ {out_name} 으로 저장"]
                        log_text = "\n".join(log_lines)
                        with open(os.path.join(out_folder, "_합치기_정보.txt"), 'w', encoding='utf-8') as f:
                            f.write(log_text)

                        done.append(out_name)
                    else:
                        for info, nm in files_only:
                            info.filename = nm
                            zf.extract(info, out_folder)
                        done.append(stem + "/")

            shutil.move(zip_path, os.path.join(out_folder, zip_name))
        except Exception as e:
            errors.append({"file": zip_name, "error": str(e)})

    return jsonify({"ok": True, "done": done, "errors": errors})


@app.route("/clean-name")
def clean_name_api():
    raw = request.args.get("name", "")
    stem = re.sub(r'\.[^.]+$', '', raw).strip()
    result = clean_name(stem)
    return jsonify({"original": raw, "cleaned": result})


if __name__ == "__main__":
    config = load_config()
    port = config.get("port", 7823)
    raw = config.get("downloads_dir", "")
    resolved = resolve_downloads_dir(raw)
    print(f"서버 시작: http://localhost:{port}")
    print(f"다운로드 폴더: {resolved}")
    if not os.path.isdir(resolved):
        print("경고: 폴더가 존재하지 않습니다.")
    _warm_file_cache(resolved)
    app.run(port=port, debug=False)
