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

ALLOWED_RENAME_EXTS = {'.txt', '.epub', '.zip'}

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

# ── 복합어 / 고유명사 사전 ────────────────────────────────────────
from compound_words import COMPOUND_WORDS

# 고유명사 사전: 이미 굳어진 소설 제목 / 시리즈명 — 절대 분리 금지
# (공백 없이 붙여 쓰는 브랜드형 제목만 등록. 공백 포함 제목은 등록 금지)
PROPER_NOUNS = frozenset({
    "갓오브블랙필드", "곤륜마협", "검신검마", "화산귀환", "전지적독자시점",
    "나혼자만렙뉴비", "나혼자레벨업", "나혼자만레벨업",
})

# 직업·신분 명사 사전: 앞에 수식어가 붙어있으면 공백 추가
# (COMPOUND_WORDS에 포함된 복합어는 그대로 유지됨)
_JOB_WORDS = [
    "변호사", "판사",
    "배우", "작가", "감독", "코치",
    "투수", "포수", "타자", "선수",
    "교수", "강사", "교사",
    "기자", "아나운서",
]
_COMPOUND_SET = frozenset(COMPOUND_WORDS)

# ── 모듈 로드 시 패턴 미리 컴파일 (호출마다 re.compile 방지) ──────────
_COMPOUND_REPAIR = []
for _w in COMPOUND_WORDS:
    _COMPOUND_REPAIR.append((_w, [
        re.compile(re.escape(_w[:i]) + r'\s+' + re.escape(_w[i:]))
        for i in range(1, len(_w))
    ]))

_PROPER_NOUN_REPAIR = []
for _n in PROPER_NOUNS:
    _PROPER_NOUN_REPAIR.append((_n, [
        re.compile(re.escape(_n[:i]) + r'\s+' + re.escape(_n[i:]))
        for i in range(1, len(_n))
    ]))

_JOB_PATTERNS = [
    (job, re.compile(rf'([가-힣]{{2,}})({re.escape(job)})(?![가-힣])'))
    for job in _JOB_WORDS
]

_RE_GRADE   = re.compile(r'([A-Za-z0-9가-힣])\s+급(?![가-힣])')
_RE_PERCENT = re.compile(r'(\S)\s+%')
_RE_HOICA   = re.compile(r'(\d+회)\s+차(?![가-힣])')
_RE_MIWAN1  = re.compile(r'미\s+완')
_RE_MIWAN2  = re.compile(r'(?<!\s)미완$')
_RE_WAN     = re.compile(r'(?<!\s)(?<!미)완$')
_RE_MANE    = re.compile(r'(\d+(?:년|일|월|주|시간|분|초)?)만에')
_RE_BUNUI   = re.compile(r'(\d+(?:억|조|천|백|만)?)분의\s*(\d+)')
_RE_NUM_KOR = re.compile(r'(\d)([가-힣]{2,})')
_RE_NUM_ORDINAL = re.compile(r'(\d+번)([가-힣]{2,})')  # "4번타자" → "4번 타자"
_RE_SU      = re.compile(r'([가-힣])수\s*(있|없)')
_RE_GEOT    = re.compile(r'([가-힣])것(?![가-힣])')
_RE_PPUN    = re.compile(r'([가-힣]{2,})뿐(?!이|인|만|도|이다|이야)')
_RE_JI      = re.compile(r'([가-힣]{2,}(?:온|간|된|난|한|본|쓴|먹은|떠난))지(?!금|역|방|식|구|도|부|하|인|원)')
_RE_MANKEUM = re.compile(r'([가-힣]{2,})만큼')
_RE_DAERO   = re.compile(r'([가-힣]{2,})대로(?![가-힣])')
_RE_DEUNG   = re.compile(r'([가-힣]{2,})등(?!급|록|장|수|지|화|자|용|반|원)')
_RE_ADV     = re.compile(
    r'(?:너무|계속|정말|매우|아직|항상|드디어|갑자기|천천히|조금|많이|다시'
    r'|이미|이제|결국|혼자|몰래|잠시|홀로|마침내|비로소|여전히|줄곧|오히려'
    r'|그냥|그저|슬쩍|억지로|가만히|가득|더욱|점점|날로|부쩍|새삼|아무래도'
    r'|어쩌다|어차피|어쩔수없이|하필|괜히|엉뚱하게|무심코|문득)([가-힣])'
)
_RE_SOK  = re.compile(r'([가-힣]{2,})속(?!도|편|성|내|임|셈|담|말|력|이)')
_RE_JUNG = re.compile(r'([가-힣]{2,})중(?!요|간|앙|심|단|학|고|반|독)')
_RE_NAE  = re.compile(r'([가-힣]{2,})내(?!부|용|면|과|역|심|기)')
_RE_GAN  = re.compile(r'([가-힣]{2,})간(?!호|단|식|격|부|파)')
_RE_WI   = re.compile(r'([가-힣]{2,})위(?!기|험|반|협|엄|치|해|장)')
_RE_BAK  = re.compile(r'([가-힣]{2,})밖(?!에)')
_RE_ADJ  = re.compile(
    r'(검은|붉은|강한|약한|새로운|낡은|큰|작은|긴|짧은|밝은|어두운'
    r'|차가운|뜨거운|깊은|얕은|넓은|좁은|높은|낮은|무거운|가벼운'
    r'|빠른|느린|많은|적은|이상한|평범한|특별한|외로운|슬픈|기쁜'
    r'|어린|늙은|젊은|예쁜|못생긴|착한|나쁜|이상한|다른|같은)([가-힣])'
)
_RE_WON    = re.compile(r'(\d+(?:억|조|천|백|만)?)원(?![가-힣])')
_RE_SPACES = re.compile(r' +')


def _job_repl(m, _job=""):
    full = m.group(0)
    if full in _COMPOUND_SET:
        return full
    for cw in _COMPOUND_SET:
        if cw.endswith(_job) and full.endswith(cw):
            return full
    return m.group(1) + ' ' + m.group(2)


def _apply_rules(s):
    """파일명 띄어쓰기 교정 — 사전+규칙 기반 (Kiwi 불사용)"""

    # ── 1차: 복합어·고유명사 보호 ────────────────────────────────────
    for word, pats in _COMPOUND_REPAIR:
        if word not in s:
            for pat in pats:
                if pat.search(s):
                    s = pat.sub(word, s)
                    break
    for noun, pats in _PROPER_NOUN_REPAIR:
        if noun not in s:
            for pat in pats:
                if pat.search(s):
                    s = pat.sub(noun, s)
                    break

    s = _RE_GRADE.sub(r'\1급', s)
    s = _RE_PERCENT.sub(r'\1%', s)
    s = _RE_HOICA.sub(r'\1차', s)
    s = _RE_MIWAN1.sub('미완', s)
    s = _RE_MIWAN2.sub(' 미완', s)
    s = _RE_WAN.sub(' 완', s)

    # ── 2차: 의존명사 ────────────────────────────────────────────────
    s = _RE_MANE.sub(r'\1 만에', s)
    s = _RE_BUNUI.sub(r'\1 분의 \2', s)
    s = _RE_NUM_ORDINAL.sub(r'\1 \2', s)
    s = _RE_NUM_KOR.sub(r'\1 \2', s)
    s = _RE_SU.sub(r'\1 수 \2', s)
    s = _RE_GEOT.sub(r'\1 것', s)
    s = _RE_PPUN.sub(r'\1 뿐', s)
    s = _RE_JI.sub(r'\1 지', s)
    s = _RE_MANKEUM.sub(r'\1 만큼', s)
    s = _RE_DAERO.sub(r'\1 대로', s)
    s = _RE_DEUNG.sub(r'\1 등', s)

    # ── 3차: 부사 ────────────────────────────────────────────────────
    s = _RE_ADV.sub(lambda m: m.group(0)[:-len(m.group(1))] + ' ' + m.group(1), s)

    # ── 4차: 위치 의존명사 ───────────────────────────────────────────
    s = _RE_SOK.sub(r'\1 속', s)
    s = _RE_JUNG.sub(r'\1 중', s)
    s = _RE_NAE.sub(r'\1 내', s)
    s = _RE_GAN.sub(r'\1 간', s)
    s = _RE_WI.sub(r'\1 위', s)
    s = _RE_BAK.sub(r'\1 밖', s)

    # ── 5차: 관형사 ──────────────────────────────────────────────────
    s = _RE_ADJ.sub(r'\1 \2', s)

    # ── 6차: 숫자+단위 ───────────────────────────────────────────────
    s = _RE_WON.sub(r'\1 원', s)

    # ── 7차: 직업 사전 ───────────────────────────────────────────────
    for _job, pat in _JOB_PATTERNS:
        s = pat.sub(lambda m, j=_job: _job_repl(m, _job=j), s)

    # ── 최종: 복합어 복원 ────────────────────────────────────────────
    for word, pats in _COMPOUND_REPAIR:
        if word not in s:
            for pat in pats:
                if pat.search(s):
                    s = pat.sub(word, s)
                    break

    s = _RE_SPACES.sub(' ', s).strip()
    return s


def fix_spacing(text):
    """파일명 띄어쓰기 교정 - 음절 분리 정규화 후 규칙 재적용"""
    # 음절 분리 정규화 먼저 (join_single_syllables 로직 재사용)
    # "네 임드" → "네임드", "게임 속 기사" → 속은 의존명사라 그대로
    parts = text.split(' ')
    merged = []
    run = []
    for t in parts:
        if re.match(r'^[가-힣]{1,2}$', t) and t not in _TITLE_MARKERS:
            # 2자 토큰이 1자 토큰 뒤 && run 길이 2+: 단어 경계 → run 분리
            # 예) ["예술","고","음악"] → "예술고" + "음악" (예술고음악 방지)
            if len(t) == 2 and len(run) >= 2 and len(run[-1]) == 1:
                _flush_run(run, merged, False)
                run = [t]
            else:
                run.append(t)
        else:
            nxt_long = bool(re.match(r'^[가-힣]{3,}$', t))
            _flush_run(run, merged, nxt_long)
            run = []
            merged.append(t)
    _flush_run(run, merged, False)
    s = ' '.join(r for r in merged if r)
    return _apply_rules(s)




EXT_STOPWORDS = {"txt", "pdf", "doc", "docx", "zip", "rar", "alz", "hwp",
                 "xlsx", "pptx", "mp3", "mp4", "jpg", "png", "gif", "exe",
                 "mb", "kb", "gb", "tb", "pb"}

def strip_episode(text):
    """숫자-숫자(화수 패턴)부터 뒷부분 제거 → 순수 제목만 추출"""
    return re.sub(r'\s*\d+[-~]\d+.*$', '', text).strip()


_TITLE_MARKERS = {'완', '완결', '미완', '후기', '후', '외전', '외', '번외', '부'}

# 이 단음절은 의존명사/후치사이므로 음절 합치기 대상에서 제외
_DEP_NOUN_CHARS = {'속', '중', '내', '간', '위', '밖', '등', '수', '뿐', '것', '및', '듯'}

def join_single_syllables(text):
    """한글이 한 글자씩 공백으로 분리된 경우 합치기"""
    parts = text.split(" ")

    # run: 연속된 1-2자 한글 토큰(마커 제외)
    # - 2개 이상 + 1자 토큰 포함 + 의존명사 단음절 없음 → 합침
    # - 4개 이상인 경우 바로 뒤에 3자+ 한글이 오면 서술형 → 합치지 않음
    # 예) "네 임드" → "네임드"  |  "게임 속 기사" → 속은 의존명사 → 그대로
    result = []
    run = []
    for part in parts:
        if re.match(r"^[가-힣]{1,2}$", part) and part not in _TITLE_MARKERS:
            # 2자 토큰이 1자 토큰 뒤 && run 길이 2+: 단어 경계 → run 분리
            if len(part) == 2 and len(run) >= 2 and len(run[-1]) == 1:
                _flush_run(run, result, False)
                run = [part]
            else:
                run.append(part)
        else:
            next_long_korean = bool(re.match(r"^[가-힣]{3,}$", part))
            _flush_run(run, result, next_long_korean)
            run = []
            result.append(part)
    _flush_run(run, result, False)
    return " ".join(r for r in result if r)


def _flush_run(run, result, next_long_korean):
    if len(run) < 2 or not any(len(p) == 1 for p in run):
        result.extend(run)
        return
    has_dep_noun = any(p in _DEP_NOUN_CHARS for p in run if len(p) == 1)
    if has_dep_noun:
        result.extend(run)
        return
    # 4개 이상 장문 run은 서술형 제목 가능성 → 뒤에 장문 한글 오면 합치지 않음
    if len(run) >= 4 and next_long_korean:
        result.extend(run)
        return
    result.append("".join(run))


def score_filename(query_words, filename):
    # 화수 패턴 이후 제거 후 순수 제목으로만 비교
    name_no_ext = join_single_syllables(strip_episode(Path(filename).stem.lower()))
    file_words = {
        w for w in re.findall(r"[가-힣a-z]+", name_no_ext)
        if len(w) >= 2 and w not in EXT_STOPWORDS
    }

    # ── 한글 공백 무시 비교 ──────────────────────────────────────────
    # "서리명가 검술천재로 회귀했다" ↔ "서리 명가 검술 천재로 회귀했다"
    file_joined = re.sub(r'[^가-힣a-z]', '', name_no_ext)
    query_kor = [qw for qw in query_words
                 if re.match(r'^[가-힣]+$', qw) and len(qw) >= 2]
    joined_score = 0.0
    if query_kor and file_joined:
        if all(qw in file_joined for qw in query_kor):
            # 모든 쿼리 단어가 파일 제목(공백 제거)에 포함 → 제목 일치
            coverage = sum(len(qw) for qw in query_kor) / len(file_joined)
            joined_score = 0.7 + 0.25 * min(coverage, 1.0)
        else:
            # 긴 단어 개별 체크 (화산천마 ↔ 화산 천마)
            for qw in query_kor:
                if len(qw) >= 4:
                    if qw == file_joined:
                        joined_score = max(joined_score, 0.9)
                    elif qw in file_joined or file_joined in qw:
                        joined_score = max(joined_score, 0.6)

    # ── 단어 매칭 ────────────────────────────────────────────────────
    common = query_words & file_words
    score = len(common)
    unmatched = query_words - common
    for qw in unmatched:
        if len(qw) < 2:
            continue
        for fw in file_words:
            if qw in fw or fw in qw:
                score += 0.7
                break
    normal_score = score / max(len(query_words), len(file_words), 1) if score > 0 else 0.0

    result = max(joined_score, normal_score)
    if result > 0:
        return result

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
    # 특수문자 제거 (■ & → 제외)
    s = re.sub(r'[^\w가-힣\s\-_()\[\]★♥~+/∕■&→﻿]', '', s)
    s = s.replace('﻿', '')  # BOM 제거
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
    s = join_single_syllables(s)  # 무협/외래어 음절 분리 교정 (능 천신 제 → 능천신제)
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
    max_results = config.get("max_results", 30)
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
        if not is_exact:
            # 한글 공백 제거 비교: 모든 쿼리 단어가 파일 joined 제목에 포함되면 exact
            raw_joined = re.sub(r'[^가-힣a-z]', '', join_single_syllables(Path(f).stem.lower()))
            clean_joined = re.sub(r'[^가-힣a-z]', '', join_single_syllables(cstem.lower())) if cstem else ""
            qkor = [qw for qw in query_words if re.match(r'^[가-힣]+$', qw) and len(qw) >= 2]
            if qkor:
                is_exact = (all(qw in raw_joined for qw in qkor) or
                            all(qw in clean_joined for qw in qkor))
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

    # 허용된 확장자만 수정 가능 (.txt, .epub, .zip)
    old_ext = Path(old_name).suffix.lower()
    if old_ext not in ALLOWED_RENAME_EXTS:
        return jsonify({"error": f"지원하지 않는 형식: {old_ext}"}), 400

    # 안전 문자 검사 (경로 탈출 방지)
    if any(c in new_name for c in ["\\", "..", ":"]):
        return jsonify({"error": "허용되지 않는 문자"}), 400
    # '/' 는 파일시스템 경로 구분자이므로 시각적으로 동일한 ∕ (U+2215)로 치환
    new_name = new_name.replace("/", "∕")

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
        if p.suffix.lower() not in ALLOWED_RENAME_EXTS:
            skipped += 1
            continue
        new_stem = clean_name(p.stem).replace("/", "∕")
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


@app.route("/epub-convert", methods=["GET", "POST"])
def epub_convert():
    import shutil as _shutil
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    filename = request.args.get("filename", "").strip()

    if not filename:
        return jsonify({"error": "파일명 없음"}), 400

    # calibre 설치 확인
    ebook_convert = _shutil.which("ebook-convert")
    if not ebook_convert:
        return jsonify({
            "error": "calibre 미설치",
            "install": "sudo apt install calibre"
        }), 503

    # epub 파일 찾기
    epub_path = None
    for root, _, files in os.walk(downloads_dir):
        if filename in files:
            epub_path = os.path.join(root, filename)
            break

    if not epub_path or not os.path.isfile(epub_path):
        return jsonify({"error": f"파일 없음: {filename}"}), 404

    stem = re.sub(r'\.epub$', '', filename, flags=re.IGNORECASE)
    folder = os.path.join(os.path.dirname(epub_path), stem)

    try:
        os.makedirs(folder, exist_ok=True)
        new_epub = os.path.join(folder, filename)
        shutil.move(epub_path, new_epub)

        txt_name = stem + ".txt"
        txt_path = os.path.join(folder, txt_name)

        result = subprocess.run(
            [ebook_convert, new_epub, txt_path],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return jsonify({"error": "변환 실패", "detail": result.stderr[-500:]}), 500

        _invalidate_file_cache()
        _warm_file_cache(downloads_dir)
        return jsonify({"ok": True, "folder": stem, "txt": txt_name})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


_epub_status = {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "succeeded": [], "failures": []}

@app.route("/epub-convert-status")
def epub_convert_status():
    return jsonify(_epub_status)


@app.route("/epub-batch-convert", methods=["POST"])
def epub_batch_convert():
    import shutil as _shutil
    import threading as _threading
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    fail_dir = os.path.join(downloads_dir, "epub변환실패")

    ebook_convert = _shutil.which("ebook-convert")
    if not ebook_convert:
        return jsonify({"error": "calibre 미설치", "install": "sudo apt install calibre"}), 503

    epub_files = []
    for root, dirs, files in os.walk(downloads_dir):
        dirs[:] = [d for d in dirs if d != "epub변환실패"]
        for f in files:
            if f.lower().endswith(".epub"):
                epub_files.append(os.path.join(root, f))

    if not epub_files:
        return jsonify({"ok": True, "started": 0, "message": "변환할 epub 없음"})

    if _epub_status["running"]:
        return jsonify({"error": "이미 변환 중", "status": _epub_status}), 409

    _epub_status.update({"running": True, "total": len(epub_files), "done": 0, "failed": 0, "current": "", "succeeded": [], "failures": []})

    def _is_korean(path):
        for enc in ("utf-8", "cp949"):
            try:
                text = open(path, encoding=enc, errors="strict").read(3000)
                korean = len(re.findall(r"[가-힣]", text))
                ratio = korean / max(len(text.replace(" ", "").replace("\n", "")), 1)
                return ratio >= 0.1
            except Exception:
                continue
        return False

    def _move_to_fail(epub_path):
        try:
            os.makedirs(fail_dir, exist_ok=True)
            _shutil.move(epub_path, os.path.join(fail_dir, os.path.basename(epub_path)))
        except Exception:
            pass

    def _convert():
        import tempfile
        for epub_path in epub_files:
            if not os.path.isfile(epub_path):
                continue
            filename = os.path.basename(epub_path)
            _epub_status["current"] = filename
            total = _epub_status["total"]
            idx = _epub_status["done"] + _epub_status["failed"] + 1
            print(f"[epub변환] ({idx}/{total}) {filename}", flush=True)
            stem = re.sub(r"\.epub$", "", filename, flags=re.IGNORECASE)
            txt_path = os.path.join(os.path.dirname(epub_path), stem + ".txt")
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt")
            os.close(tmp_fd)
            try:
                result = subprocess.run(
                    [ebook_convert, epub_path, tmp_path],
                    capture_output=True, text=True, timeout=300
                )
                if result.returncode != 0 or not os.path.isfile(tmp_path):
                    _move_to_fail(epub_path)
                    _epub_status["failed"] += 1
                    _epub_status["failures"].append(filename)
                    print(f"[epub변환] ✗ 변환실패: {filename}", flush=True)
                    continue

                if _is_korean(tmp_path):
                    _shutil.move(tmp_path, txt_path)
                    os.remove(epub_path)
                    _epub_status["done"] += 1
                    _epub_status["succeeded"].append(filename)
                    print(f"[epub변환] ✓ 완료: {filename}", flush=True)
                else:
                    _move_to_fail(epub_path)
                    _epub_status["failed"] += 1
                    _epub_status["failures"].append(filename)
                    print(f"[epub변환] ✗ 한글미달: {filename}", flush=True)
            except Exception as e:
                _move_to_fail(epub_path)
                _epub_status["failed"] += 1
                _epub_status["failures"].append(filename)
                print(f"[epub변환] ✗ 오류: {filename} — {e}", flush=True)
            finally:
                try: os.remove(tmp_path)
                except Exception: pass
        _epub_status["running"] = False
        _epub_status["current"] = ""
        print(f"[epub변환] 완료 — 성공 {_epub_status['done']}개 / 실패 {_epub_status['failed']}개", flush=True)
        _invalidate_file_cache()
        _warm_file_cache(downloads_dir)

    _threading.Thread(target=_convert, daemon=True).start()
    return jsonify({"ok": True, "started": len(epub_files)})


def _history_path():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    archive_folder = config.get("archive_folder", "소설")
    return os.path.join(downloads_dir, archive_folder, ".reader_history.json")

def _load_history():
    try:
        import json as _j
        return _j.load(open(_history_path(), encoding="utf-8"))
    except Exception:
        return []

def _save_history(data):
    try:
        import json as _j
        _j.dump(data, open(_history_path(), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass


@app.route("/history")
def get_history():
    return jsonify(_load_history())


@app.route("/history/save", methods=["POST"])
def save_history():
    import datetime
    body = request.get_json(silent=True) or {}
    filename = body.get("filename", "").strip()
    position = float(body.get("position", 0))
    if not filename:
        return jsonify({"error": "파일명 없음"}), 400
    hist = _load_history()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    hist = [h for h in hist if h.get("filename") != filename]
    hist.insert(0, {"filename": filename, "position": position, "opened_at": now})
    _save_history(hist)
    return jsonify({"ok": True})


@app.route("/history/delete", methods=["POST"])
def delete_history():
    body = request.get_json(silent=True) or {}
    filename = body.get("filename", "").strip()
    _save_history([h for h in _load_history() if h.get("filename") != filename])
    return jsonify({"ok": True})


@app.route("/history/clear", methods=["POST"])
def clear_history():
    _save_history([])
    return jsonify({"ok": True})


@app.route("/view")
def view_file():
    filename = request.args.get("filename", "").strip()
    if not filename:
        return jsonify({"error": "파일명 없음"}), 400
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    for root, dirs, files in os.walk(downloads_dir):
        if filename in files:
            path = os.path.join(root, filename)
            for enc in ("utf-8", "cp949"):
                try:
                    content = open(path, encoding=enc, errors="strict").read()
                    return jsonify({"ok": True, "content": content})
                except Exception:
                    continue
            content = open(path, encoding="utf-8", errors="replace").read()
            return jsonify({"ok": True, "content": content})
    return jsonify({"error": "파일 없음"}), 404


@app.route("/reading-status", methods=["GET", "POST", "DELETE"])
def reading_status_api():
    from datetime import datetime as _dt
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    archive = config.get("archive_folder", "소설")
    status_file = os.path.join(downloads_dir, archive, "reading_status.json")

    def _load():
        if os.path.isfile(status_file):
            with open(status_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save(data):
        os.makedirs(os.path.dirname(status_file), exist_ok=True)
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    if request.method == "GET":
        return jsonify(_load())

    if request.method == "DELETE":
        fname = (request.args.get("filename") or "").strip()
        if not fname:
            return jsonify({"error": "filename 없음"}), 400
        data = _load()
        data.pop(fname, None)
        _save(data)
        return jsonify({"ok": True})

    # POST — 상태 저장
    body = request.get_json(silent=True) or {}
    fname  = body.get("filename", "").strip()
    status = body.get("status", "").strip()
    if not fname or status not in ("포기", "다읽음"):
        return jsonify({"error": "invalid"}), 400
    data = _load()
    data[fname] = {"status": status, "date": _dt.now().strftime("%Y-%m-%d"), "ts": int(_dt.now().timestamp())}
    _save(data)
    return jsonify({"ok": True})


def _novel_data_path():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    archive = config.get("archive_folder", "소설")
    return os.path.join(downloads_dir, archive, "List.json")

def _load_novel_data():
    p = _novel_data_path()
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # 기존 파일에서 마이그레이션
    data = {}
    try:
        for h in _load_history():
            fn = h.get("filename", "")
            if fn:
                data[fn] = {"status": "기록", "position": h.get("position", 0), "opened_at": h.get("opened_at", "")}
    except Exception:
        pass
    try:
        config2 = load_config()
        sf = os.path.join(resolve_downloads_dir(config2.get("downloads_dir", "")), config2.get("archive_folder", "소설"), "reading_status.json")
        if os.path.isfile(sf):
            with open(sf, "r", encoding="utf-8") as f:
                statuses = json.load(f)
            for fn, info in statuses.items():
                if fn not in data:
                    data[fn] = {"status": info.get("status", "기록"), "position": 0, "opened_at": info.get("date", "")}
                else:
                    data[fn]["status"] = info.get("status", "기록")
    except Exception:
        pass
    if data:
        _save_novel_data(data)
    return data

def _save_novel_data(data):
    p = _novel_data_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route("/novel-data", methods=["GET", "POST", "DELETE"])
def novel_data_api():
    import datetime as _dt_mod
    if request.method == "GET":
        return jsonify(_load_novel_data())
    if request.method == "DELETE":
        fname = (request.args.get("filename") or "").strip()
        if not fname:
            return jsonify({"error": "filename 없음"}), 400
        data = _load_novel_data()
        data.pop(fname, None)
        _save_novel_data(data)
        return jsonify({"ok": True})
    # POST
    body = request.get_json(silent=True) or {}
    fname = body.get("filename", "").strip()
    if not fname:
        return jsonify({"error": "filename 없음"}), 400
    data = _load_novel_data()
    entry = data.get(fname, {})
    if "status" in body:
        entry["status"] = body["status"]
    if "position" in body:
        entry["position"] = float(body["position"])
        entry["opened_at"] = _dt_mod.datetime.now().isoformat(timespec="seconds")
    if "status" not in entry:
        entry["status"] = "기록"
    data[fname] = entry
    _save_novel_data(data)
    return jsonify({"ok": True})


@app.route("/clean-name")
def clean_name_api():
    raw = request.args.get("name", "")
    stem = re.sub(r'\.[^.]+$', '', raw).strip()
    result = clean_name(stem)
    return jsonify({"original": raw, "cleaned": result})


@app.route("/manifest.json")
def pwa_manifest():
    return json.dumps({
        "name": "소설 뷰어",
        "short_name": "소설 뷰어",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1e1e2e",
        "theme_color": "#1e1e2e",
        "icons": [
            {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}
        ]
    }, ensure_ascii=False), 200, {"Content-Type": "application/manifest+json"}

@app.route("/icon.svg")
def pwa_icon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="80" fill="#1e1e2e"/><text x="256" y="340" font-size="320" text-anchor="middle">📚</text></svg>'
    return svg, 200, {"Content-Type": "image/svg+xml"}

@app.route("/sw.js")
def service_worker():
    js = """self.addEventListener('install',e=>e.waitUntil(self.skipWaiting()));
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>e.respondWith(fetch(e.request).catch(()=>new Response('오프라인',{headers:{'Content-Type':'text/plain;charset=utf-8'}}))));"""
    return js, 200, {"Content-Type": "application/javascript"}

@app.route("/")
def web_index():
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>소설 뷰어</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#1e1e2e">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="소설 뷰어">
<link rel="apple-touch-icon" href="/icon.svg">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;background:#1e1e2e;color:#cdd6f4;height:100dvh;display:flex;flex-direction:column;overflow:hidden}
#tabBar{display:flex;background:#181825;border-bottom:1px solid #313244;flex-shrink:0}
.tab-btn{flex:1;padding:10px 4px;background:none;border:none;border-bottom:2px solid transparent;color:#6c7086;font-size:12px;font-weight:700;cursor:pointer}
.tab-btn.active{color:#89b4fa;border-bottom-color:#89b4fa}
.tab-panel{display:none;flex:1;flex-direction:column;overflow:hidden}
.tab-panel.active{display:flex}
#searchPane{padding:10px;gap:8px;display:none;flex-direction:column}
#searchPane.active{display:flex}
.search-row{display:flex;gap:6px}
.search-row input{flex:1;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:6px;padding:8px 10px;font-size:13px;outline:none}
.search-row input:focus{border-color:#89b4fa}
.search-row button{background:#89b4fa;color:#1e1e2e;border:none;border-radius:6px;padding:8px 14px;font-size:12px;font-weight:700;cursor:pointer;flex-shrink:0}
.list-scroll{flex:1;overflow-y:auto;padding:4px 10px}
.item{display:flex;align-items:center;gap:8px;padding:10px 6px;border-bottom:1px solid #313244;cursor:pointer}
.item:active{background:#26263a}
.item-info{flex:1;overflow:hidden}
.item-name{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item-meta{font-size:11px;color:#6c7086;margin-top:2px}
.item-size{font-size:11px;color:#6c7086;flex-shrink:0}
.exact{background:#a6e3a1;border-radius:6px;margin-bottom:2px;border-bottom:none;padding:10px 8px}
.exact .item-name{color:#1e1e2e}
.exact .item-meta,.exact .item-size{color:#2d6a4f}
.det-btn{background:none;border:none;color:#89b4fa;font-size:15px;cursor:pointer;padding:0 4px;flex-shrink:0;margin-left:2px}
.det-btn:active{color:#cba6f7}
.related-section{background:#1e1e2e;border-left:2px solid #313244;margin-left:12px;margin-bottom:4px}
.related-section .item{font-size:13px;padding:6px 8px}
.del-btn{background:none;border:none;color:#45475a;font-size:16px;cursor:pointer;padding:0 4px;flex-shrink:0}
.del-btn:active{color:#f38ba8}
.back-btn{background:none;border:none;color:#89b4fa;font-size:15px;cursor:pointer;padding:0 4px;flex-shrink:0}
.empty{color:#6c7086;font-size:12px;padding:16px 0;text-align:center}
</style>
</head>
<body>
<div id="tabBar">
  <button class="tab-btn active" data-tab="search">검색</button>
  <button class="tab-btn" data-tab="history">기록</button>
  <button class="tab-btn" data-tab="finished">다읽음</button>
  <button class="tab-btn" data-tab="giveup">포기</button>
</div>
<div class="tab-panel active" id="tab-search">
  <div id="searchPane" class="active">
    <div class="search-row">
      <input id="q" placeholder="소설 제목 검색..." type="search">
      <button onclick="doSearch()">검색</button>
    </div>
    <div class="list-scroll" id="results"></div>
  </div>
</div>
<div class="tab-panel" id="tab-history"><div class="list-scroll" id="histList"></div></div>
<div class="tab-panel" id="tab-finished"><div class="list-scroll" id="finList"></div></div>
<div class="tab-panel" id="tab-giveup"><div class="list-scroll" id="gpList"></div></div>
<script>
if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
const S = '';
function relTime(s){if(!s)return'';const d=(Date.now()-new Date(s).getTime())/1000;if(d<60)return'방금';if(d<3600)return Math.floor(d/60)+'분 전';if(d<86400)return Math.floor(d/3600)+'시간 전';if(d<604800)return Math.floor(d/86400)+'일 전';return Math.floor(d/604800)+'주 전';}
function openViewer(fn){location.href='/web-viewer?filename='+encodeURIComponent(fn);}

document.querySelectorAll('.tab-btn').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-'+btn.dataset.tab).classList.add('active');
    if(btn.dataset.tab==='history') loadStatus('기록','histList',true);
    if(btn.dataset.tab==='finished') loadStatus('다읽음','finList',false);
    if(btn.dataset.tab==='giveup') loadStatus('포기','gpList',false);
  });
});

const qEl=document.getElementById('q');
qEl.addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
function stripEp(name){
  // 파일명에서 화수·완결 정보 제거 → 순수 제목
  return name.replace(/\\.txt$/i,'')
    .replace(/\\s*\\d+[-~]\\d+.*$/,'')
    .replace(/\\s*(완결?|미완|에필|후기|외전)\\s*$/,'')
    .trim();
}

function renderItem(item, isRelated){
  const name=typeof item==='object'?item.name:item;
  const d=document.createElement('div');
  d.className='item'+(item.ex?' exact':'')+(isRelated?' related':'');
  const title=name.replace(/\\.txt$/i,'');
  const size=item.size?item.size+' MB':'';
  d.innerHTML='<div class="item-info"><div class="item-name">'+title+'</div></div>'
    +'<span class="item-size">'+size+'</span>';
  // 자세히보기 버튼 (관련 파일 검색)
  const detBtn=document.createElement('button');
  detBtn.className='det-btn';detBtn.textContent='⊕';detBtn.title='관련 파일 보기';
  detBtn.addEventListener('click',e=>{
    e.stopPropagation();
    const existing=d.nextElementSibling;
    if(existing&&existing.classList.contains('related-section')){existing.remove();return;}
    const sec=document.createElement('div');sec.className='related-section';
    sec.innerHTML='<div class="empty">검색 중...</div>';
    d.insertAdjacentElement('afterend',sec);
    const cleanTitle=stripEp(name);
    fetch(S+'/search?text='+encodeURIComponent(cleanTitle)).then(r=>r.json()).then(rel=>{
      sec.innerHTML='';
      const relItems=[...(rel.exact||[]).map(i=>({...i,ex:true})),...(rel.partial||[])]
        .filter(i=>(typeof i==='object'?i.name:i).toLowerCase().endsWith('.txt'))
        .filter(i=>(typeof i==='object'?i.name:i)!==name);
      if(!relItems.length){sec.innerHTML='<div class="empty">관련 파일 없음</div>';return;}
      relItems.forEach(ri=>sec.appendChild(renderItem(ri,true)));
    });
  });
  d.appendChild(detBtn);
  d.addEventListener('click',()=>openViewer(name));
  return d;
}

function doSearch(){
  const q=qEl.value.trim();if(!q)return;
  const res=document.getElementById('results');
  res.innerHTML='<div class="empty">검색 중...</div>';
  fetch(S+'/search?text='+encodeURIComponent(q)).then(r=>r.json()).then(data=>{
    res.innerHTML='';
    const items=[...(data.exact||[]).map(i=>({...i,ex:true})),...(data.partial||[])];
    const txtItems=items.filter(i=>(typeof i==='object'?i.name:i).toLowerCase().endsWith('.txt'));
    if(!txtItems.length){res.innerHTML='<div class="empty">결과 없음</div>';return;}
    txtItems.forEach(i=>res.appendChild(renderItem(i,false)));
  }).catch(()=>{res.innerHTML='<div class="empty">오류</div>';});
}

function loadStatus(statusFilter,containerId,isHistory){
  const c=document.getElementById(containerId);
  c.innerHTML='<div class="empty">불러오는 중...</div>';
  fetch(S+'/novel-data').then(r=>r.json()).then(all=>{
    const entries=Object.entries(all)
      .filter(([,v])=>v.status===statusFilter)
      .sort((a,b)=>(b[1].opened_at||'')>(a[1].opened_at||'')?1:-1);
    c.innerHTML='';
    if(!entries.length){c.innerHTML='<div class="empty">'+statusFilter+' 목록 없음</div>';return;}
    entries.forEach(([fname,v])=>{
      const row=document.createElement('div');
      row.className='item';
      row.innerHTML='<div class="item-info"><div class="item-name">'+fname.replace(/\\.txt$/i,'')+'</div>'
        +'<div class="item-meta">'+((v.position??0).toFixed(0))+'% · '+relTime(v.opened_at)+'</div></div>';
      row.addEventListener('click',()=>openViewer(fname));
      if(!isHistory){
        const back=document.createElement('button');
        back.className='back-btn';back.textContent='↩';back.title='기록으로';
        back.addEventListener('click',e=>{e.stopPropagation();
          fetch(S+'/novel-data',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:fname,status:'기록'})})
          .then(()=>row.remove());});
        row.appendChild(back);
      }
      const del=document.createElement('button');
      del.className='del-btn';del.textContent='🗑';
      del.addEventListener('click',e=>{e.stopPropagation();
        if(!confirm('삭제하시겠습니까?'))return;
        fetch(S+'/novel-data?filename='+encodeURIComponent(fname),{method:'DELETE'}).then(()=>row.remove());});
      row.appendChild(del);
      c.appendChild(row);
    });
  }).catch(()=>{c.innerHTML='<div class="empty">오류</div>';});
}
</script>
</body>
</html>"""


@app.route("/web-viewer")
def web_viewer():
    filename = request.args.get("filename", "")
    fn_json = json.dumps(filename)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{filename.replace('.txt','')}</title>
<style>
:root{{--sb-track:#1e1e2e;--sb-thumb:rgba(255,255,255,0.13)}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;background:#1e1e2e;color:#cdd6f4;height:100dvh;display:flex;flex-direction:column;overflow:hidden}}
#topbar{{display:flex;align-items:center;gap:6px;padding:8px 10px;background:#181825;border-bottom:1px solid #313244;flex-shrink:0;flex-wrap:wrap}}
#backBtn{{background:none;border:none;color:#89b4fa;font-size:18px;cursor:pointer;padding:0 4px;flex-shrink:0}}
#title{{flex:1;font-size:12px;font-weight:700;color:#89b4fa;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}}
#chapterSelect{{background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:3px 4px;font-size:11px;max-width:140px;cursor:pointer}}
#posInfo{{font-size:11px;color:#6c7086;flex-shrink:0}}
.topbar-select{{background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:3px 5px;font-size:11px;cursor:pointer;flex-shrink:0}}
.tbtn{{background:none;border:1px solid #45475a;color:#cdd6f4;border-radius:4px;padding:3px 8px;font-size:11px;cursor:pointer;flex-shrink:0;white-space:nowrap}}
.tbtn:active{{background:#313244}}
.tbtn.saved{{color:#a6e3a1;border-color:#a6e3a1}}
#settingsPanel{{display:none;background:#181825;border-bottom:1px solid #313244;padding:10px 12px;flex-shrink:0;gap:10px;flex-wrap:wrap;align-items:center}}
#settingsPanel.open{{display:flex}}
.sg{{display:flex;align-items:center;gap:5px;white-space:nowrap}}
.sl{{font-size:11px;color:#6c7086;min-width:44px}}
.sg input[type=range]{{width:80px;accent-color:#89b4fa}}
.sg input[type=color]{{width:28px;height:22px;border:1px solid #45475a;border-radius:3px;background:none;cursor:pointer;padding:1px}}
.sg select{{background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:2px 4px;font-size:11px}}
.sv{{font-size:11px;color:#a6adc8;min-width:26px}}
#resetBtn{{background:#313244;border:1px solid #45475a;color:#f38ba8;border-radius:4px;padding:3px 8px;font-size:11px;cursor:pointer}}
#content{{flex:1;overflow-y:auto;padding:20px 5%;line-height:2;font-size:15px;white-space:pre-wrap;word-break:break-word;scrollbar-color:var(--sb-thumb) var(--sb-track);scrollbar-width:thin}}
#content::-webkit-scrollbar{{width:4px}}
#content::-webkit-scrollbar-track{{background:var(--sb-track)}}
#content::-webkit-scrollbar-thumb{{background:var(--sb-thumb);border-radius:2px}}
#loading{{display:flex;align-items:center;justify-content:center;flex:1;color:#6c7086;font-size:14px;flex-direction:column;gap:12px}}
.load-actions{{display:flex;gap:8px}}
.load-actions button{{border:1px solid #45475a;border-radius:6px;padding:7px 18px;font-size:12px;cursor:pointer;background:#313244;color:#cdd6f4}}
.load-actions .ok{{color:#a6e3a1;border-color:#a6e3a1}}
.ch{{display:block;color:#89b4fa;font-weight:700;font-size:13px;margin:32px 0 8px;padding-top:8px;border-top:1px solid #313244}}
.ch:first-child{{margin-top:0;border-top:none}}
</style>
</head>
<body>
<div id="topbar">
  <button id="backBtn" onclick="history.back()">←</button>
  <span id="title"></span>
  <select id="chapterSelect" style="display:none"></select>
  <span id="posInfo"></span>
  <select class="topbar-select" id="statusSelect">
    <option value="기록">기록</option>
    <option value="포기">포기</option>
    <option value="다읽음">다읽음</option>
  </select>
  <button class="tbtn" id="saveStatusBtn">상태저장</button>
  <button class="tbtn" id="savePosBtn">위치저장</button>
  <button class="tbtn" id="settingsBtn">⚙</button>
</div>
<div id="settingsPanel">
  <div class="sg"><span class="sl">좌우여백</span><input type="range" id="sPadding" min="0" max="20" step="1"><span class="sv" id="vPadding"></span></div>
  <div class="sg"><span class="sl">글씨체</span>
    <select id="sFont">
      <option value="'Malgun Gothic','Apple SD Gothic Neo',sans-serif">기본</option>
      <option value="'Nanum Gothic',sans-serif">나눔고딕</option>
      <option value="'Nanum Myeongjo',serif">나눔명조</option>
      <option value="serif">명조</option>
    </select>
  </div>
  <div class="sg"><span class="sl">글씨크기</span><input type="range" id="sFontSize" min="12" max="28" step="1"><span class="sv" id="vFontSize"></span></div>
  <div class="sg"><span class="sl">줄간격</span><input type="range" id="sLineHeight" min="1.2" max="3.5" step="0.1"><span class="sv" id="vLineHeight"></span></div>
  <div class="sg"><span class="sl">배경색</span><input type="color" id="sBg"></div>
  <div class="sg"><span class="sl">글자색</span><input type="color" id="sFg"></div>
  <button id="resetBtn">기본값</button>
</div>
<div id="loading"><span>불러오는 중...</span></div>
<div id="content" style="display:none"></div>
<script>
const filename = {fn_json};
const S = '';
const DEFAULTS = {{padding:5,font:"'Malgun Gothic','Apple SD Gothic Neo',sans-serif",fontSize:16,lineHeight:2.0,bg:'#1e1e2e',fg:'#cdd6f4'}};
const LS_KEY = 'viewer_style';
const contentEl = document.getElementById('content');

document.getElementById('title').textContent = filename.replace(/\\.txt$/i,'');
document.title = filename.replace(/\\.txt$/i,'');

function loadStyle(){{try{{return Object.assign({{}},DEFAULTS,JSON.parse(localStorage.getItem(LS_KEY)||'{{}}'));}}catch{{return{{...DEFAULTS}};}}}}
function saveStyle(st){{localStorage.setItem(LS_KEY,JSON.stringify(st));}}
function hexLum(hex){{const r=parseInt(hex.slice(1,3),16)/255,g=parseInt(hex.slice(3,5),16)/255,b=parseInt(hex.slice(5,7),16)/255;return 0.299*r+0.587*g+0.114*b;}}
function applyStyle(st){{
  contentEl.style.padding=`20px ${{st.padding}}%`;
  contentEl.style.fontFamily=st.font;
  contentEl.style.fontSize=st.fontSize+'px';
  contentEl.style.lineHeight=st.lineHeight;
  document.body.style.background=st.bg;
  contentEl.style.color=st.fg;
  const r=document.documentElement;
  r.style.setProperty('--sb-track',st.bg);
  r.style.setProperty('--sb-thumb',hexLum(st.bg)<0.5?'rgba(255,255,255,0.13)':'rgba(0,0,0,0.15)');
}}
function syncUI(st){{
  document.getElementById('sPadding').value=st.padding;
  document.getElementById('sFontSize').value=st.fontSize;
  document.getElementById('sLineHeight').value=st.lineHeight;
  document.getElementById('sBg').value=st.bg;
  document.getElementById('sFg').value=st.fg;
  document.getElementById('vPadding').textContent=st.padding+'%';
  document.getElementById('vFontSize').textContent=st.fontSize+'px';
  document.getElementById('vLineHeight').textContent=parseFloat(st.lineHeight).toFixed(1);
  const sel=document.getElementById('sFont');
  for(const o of sel.options)if(o.value===st.font){{sel.value=st.font;break;}}
}}
let curStyle=loadStyle();
applyStyle(curStyle);
syncUI(curStyle);

document.getElementById('settingsBtn').addEventListener('click',()=>{{
  const p=document.getElementById('settingsPanel');
  p.classList.toggle('open');
}});
function onChange(){{
  curStyle={{
    padding:parseInt(document.getElementById('sPadding').value),
    font:document.getElementById('sFont').value,
    fontSize:parseInt(document.getElementById('sFontSize').value),
    lineHeight:parseFloat(document.getElementById('sLineHeight').value),
    bg:document.getElementById('sBg').value,
    fg:document.getElementById('sFg').value,
  }};
  document.getElementById('vPadding').textContent=curStyle.padding+'%';
  document.getElementById('vFontSize').textContent=curStyle.fontSize+'px';
  document.getElementById('vLineHeight').textContent=curStyle.lineHeight.toFixed(1);
  applyStyle(curStyle);saveStyle(curStyle);
}}
['sPadding','sFont','sFontSize','sLineHeight','sBg','sFg'].forEach(id=>document.getElementById(id).addEventListener('input',onChange));
document.getElementById('resetBtn').addEventListener('click',()=>{{curStyle={{...DEFAULTS}};syncUI(curStyle);applyStyle(curStyle);saveStyle(curStyle);}});

function getScrollPct(){{const max=contentEl.scrollHeight-contentEl.clientHeight;return max>0?Math.round(contentEl.scrollTop/max*1000)/10:0;}}
function savePosition(){{
  if(!filename)return;
  fetch(S+'/novel-data',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{filename,position:getScrollPct()}})}}).catch(()=>{{}});
}}
function saveStatus(status){{
  return fetch(S+'/novel-data',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{filename,status,position:getScrollPct()}})}});
}}

let stTimer=null,posTimer=null;
document.getElementById('saveStatusBtn').addEventListener('click',()=>{{
  saveStatus(document.getElementById('statusSelect').value).then(()=>{{
    const b=document.getElementById('saveStatusBtn');
    b.classList.add('saved');clearTimeout(stTimer);
    stTimer=setTimeout(()=>b.classList.remove('saved'),1500);
  }}).catch(()=>{{}});
}});
document.getElementById('savePosBtn').addEventListener('click',()=>{{
  savePosition();
  const b=document.getElementById('savePosBtn');
  b.classList.add('saved');clearTimeout(posTimer);
  posTimer=setTimeout(()=>b.classList.remove('saved'),1500);
}});

const CH_RE=/^(?:제\\s*\\d+\\s*화|#\\s*\\d+|\\d+\\s*화|chapter\\s*\\d+|\\[\\d+화?\\])/i;
function esc(s){{return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}

fetch(S+'/view?filename='+encodeURIComponent(filename))
  .then(r=>{{if(r.status===404)return r.json().then(j=>{{throw Object.assign(new Error(j.error||'없음'),{{notFound:true}});}});return r.json();}})
  .then(data=>{{
    const loadEl=document.getElementById('loading');
    loadEl.remove();
    contentEl.style.display='block';
    applyStyle(curStyle);
    const lines=(data.content||'').split('\\n');
    const chapters=[];let html='',ci=0;
    for(const line of lines){{
      const t=line.trim();
      if(t&&CH_RE.test(t)){{const id='ch'+ci++;chapters.push({{id,title:t}});html+=`<span class="ch" id="${{id}}">${{esc(line)}}</span>`;}}
      else html+=esc(line)+'\\n';
    }}
    contentEl.innerHTML=html;
    if(chapters.length){{
      const sel=document.getElementById('chapterSelect');
      sel.style.display='block';
      chapters.forEach(ch=>{{const o=document.createElement('option');o.value=ch.id;o.textContent=ch.title.slice(0,25);sel.appendChild(o);}});
      sel.addEventListener('change',()=>document.getElementById(sel.value)?.scrollIntoView({{behavior:'smooth'}}));
      const anchors=chapters.map(ch=>document.getElementById(ch.id));
      contentEl.addEventListener('scroll',()=>{{
        const top=contentEl.scrollTop+60;let cur=0;
        for(let i=0;i<anchors.length;i++)if(anchors[i]&&anchors[i].offsetTop<=top)cur=i;
        sel.selectedIndex=cur;
      }},{{passive:true}});
    }}
    fetch(S+'/novel-data').then(r=>r.json()).then(all=>{{
      const e=all[filename];
      if(e){{
        if(e.status)document.getElementById('statusSelect').value=e.status;
        if(e.position>0)setTimeout(()=>{{const max=contentEl.scrollHeight-contentEl.clientHeight;contentEl.scrollTop=max*e.position/100;}},150);
      }}
    }}).catch(()=>{{}});
    contentEl.addEventListener('scroll',()=>{{document.getElementById('posInfo').textContent=getScrollPct().toFixed(0)+'%';}},{{passive:true}});
  }})
  .catch(err=>{{
    const loadEl=document.getElementById('loading');
    if(err.notFound){{
      loadEl.querySelector('span').textContent='파일이 삭제되었습니다.';
      const acts=document.createElement('div');acts.className='load-actions';
      const ok=document.createElement('button');ok.className='ok';ok.textContent='기록에서 제거';
      ok.addEventListener('click',()=>{{fetch(S+'/novel-data?filename='+encodeURIComponent(filename),{{method:'DELETE'}}).catch(()=>{{}});loadEl.querySelector('span').textContent='제거했습니다.';acts.remove();}});
      const no=document.createElement('button');no.textContent='취소';
      no.addEventListener('click',()=>acts.remove());
      acts.appendChild(ok);acts.appendChild(no);loadEl.appendChild(acts);
    }}else{{loadEl.querySelector('span').textContent='파일 로드 실패';}}
  }});
</script>
</body>
</html>"""


if __name__ == "__main__":
    config = load_config()
    port = config.get("port", 7823)
    raw = config.get("downloads_dir", "")
    resolved = resolve_downloads_dir(raw)
    lan_ip = config.get("lan_ip", "")
    if not lan_ip:
        try:
            import subprocess
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '169.*' -and $_.IPAddress -notlike '172.*' -and $_.IPAddress -ne '127.0.0.1'} | Select-Object -First 1).IPAddress"],
                capture_output=True, text=True, timeout=5
            )
            lan_ip = r.stdout.strip()
        except Exception:
            lan_ip = "???"
    print(f"서버 시작: http://localhost:{port}")
    print(f"폰 접속: http://{lan_ip}:{port}")
    print(f"다운로드 폴더: {resolved}")
    if not os.path.isdir(resolved):
        print("경고: 폴더가 존재하지 않습니다.")
    _warm_file_cache(resolved)
    app.run(host="0.0.0.0", port=port, debug=False)
