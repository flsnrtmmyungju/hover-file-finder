import json
import os
import re
import shutil
import sys
from pathlib import Path

try:
    from flask import Flask, request, jsonify
    from flask_cors import CORS
except ImportError:
    print("pip install flask flask-cors")
    sys.exit(1)

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

_spacing_cache = {}
_cache_path = _BASE_DIR / "spacing_cache.json"
if _cache_path.exists():
    try:
        with open(_cache_path, encoding="utf-8") as _f:
            _spacing_cache = _json.load(_f)
    except Exception:
        pass

def _save_cache():
    try:
        with open(_cache_path, "w", encoding="utf-8") as _f:
            _json.dump(_spacing_cache, _f, ensure_ascii=False, indent=2)
    except Exception:
        pass

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
HANJA_C         = "完"        # 完


def clean_name(stem, skip_spacing=False):
    # 특수 공백 문자 → 일반 공백
    s = stem.replace('\xa0', ' ').replace('​', '').replace('　', ' ')

    # 1단계: 한자 -> 한글 (괄호 없는 단순 치환)
    s = s.replace(HANJA_COMPLETE,  "완")
    s = s.replace(HANJA_UNFINISH,  "미완")
    s = s.replace(HANJA_SIDE,      "외")
    s = s.replace(HANJA_SIDE2,     "외")
    s = s.replace(HANJA_C,         "완")
    s = s.replace(HANJA_UNFINISH1, "미완")
    # 나머지 한자 전부 삭제
    s = re.sub(r"[㐀-鿿豈-﫿]+", "", s)
    # 연재중 → 미완 (괄호 포함, 한자 삭제 후)
    s = re.sub(r"[\[\(]\s*연재\s*중\s*[\]\)]", " 미완 ", s)
    s = re.sub(r"연재\s*중", " 미완 ", s)
    s = re.sub(r"연재(?!\S)", " 미완 ", s)
    s = re.sub(r"(?<![가-힣])외전(?![가-힣])", " 외 ", s)
    s = re.sub(r"(?<![가-힣])후기(?![가-힣])", " 후 ", s)
    s = re.sub(r"(?<![가-힣])포함(?![가-힣])", " ", s)

    # 2단계: 파일명 앞 [텍스트] 처리
    m = re.match(r"^\s*\[(완결|완)\]\s*(?:완결|완)?\s*", s)
    if m:
        rest = s[m.end():].strip()
        s = rest if re.search(r"\s완$", rest) else rest + " 완"
    else:
        s = re.sub(r"^\s*\[[^\]]*\]\s*", "", s)

    # 3단계: 인라인 괄호 처리
    s = re.sub(r"[\(\[]\s*완결\s*[\)\]]", "완", s)
    s = re.sub(r"[\(\[]\s*완\s*[\)\]]",   "완", s)
    s = re.sub(r"[\(\[]\s*미완\s*[\)\]]", "미완", s)
    s = s.replace("완결", "완")

    # 4단계: 기타 정리
    s = s.replace("본편", "본")                       # 본편 → 본
    s = re.sub(r"\d+편", "", s)                       # 숫자+편 삭제 (183편 등)
    s = re.sub(r"(?<![가-힣])및(?![가-힣])", ",", s)   # 및 → ,
    # 빈 () 제거, [텍스트] 전부 제거, (txt) 등 제거
    s = re.sub(r"\(\s*\d+\s*\)", "", s)  # (1) (2) 등 숫자만 있는 괄호
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"\(\s*txt\s*\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"19N", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*@\S+$", "", s)   # @용은 등 끝에 붙은 태그 제거
    s = re.sub(r"\s*ⓒ\S*$", "", s)  # ⓒ작가명 제거
    s = s.replace("+", " ")
    s = s.replace("_", " ")
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
    # 어디서든 "미 완" → "미완" 최종 보정
    s = re.sub(r"미\s+완", "미완", s)
    # 끝 완/미완 앞 공백 보장 ("미완"의 완은 제외)
    s = re.sub(r"(?<!\s)미완$", " 미완", s)
    s = re.sub(r"(?<!\s)(?<!미)완$", " 완", s)
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

    # os.walk 한 번에 all_files + file_paths 동시 수집
    all_files = []
    file_paths = {}
    try:
        for root, dirs, files in os.walk(downloads_dir):
            for f in files:
                all_files.append(f)
                if f not in file_paths:
                    file_paths[f] = os.path.join(root, f)
    except FileNotFoundError:
        return jsonify({"error": f"폴더를 찾을 수 없음: {downloads_dir}"}), 500
    except PermissionError:
        return jsonify({"error": "폴더 접근 권한 없음"}), 500

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

    for f in all_files:
        score = score_filename(query_words, f)
        if score <= 0:
            continue
        name_no_ext = join_single_syllables(Path(f).stem.lower())
        file_words = {
            w for w in re.findall(r"[가-힣a-z]+", name_no_ext)
            if len(w) >= 2 and w not in EXT_STOPWORDS
        }
        is_exact = bool(query_words) and query_words <= file_words
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
        os.remove(target)
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
        return jsonify({"error": "같은 이름 파일 존재"}), 409

    try:
        os.rename(target, dst)
        return jsonify({"ok": True, "new_name": new_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/rename", methods=["GET", "POST"])
def rename_novels():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))

    renamed, skipped, errors = 0, 0, []
    total = sum(len(files) for _, _, files in os.walk(downloads_dir))
    processed = 0
    print(f"[이름정리] 시작 - 총 {total}개 파일", flush=True)

    for root, dirs, files in os.walk(downloads_dir):
        for f in files:
            processed += 1
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
                print(f"[이름정리] ({processed}/{total}) {f!r} → {new_name!r}", flush=True)
            except Exception as e:
                errors.append(f)

            if processed % 50 == 0:
                print(f"[이름정리] 진행 중... ({processed}/{total}) 변경 {renamed}개", flush=True)

    _save_cache()  # Kiwi 캐시 일괄 저장
    print(f"[이름정리] 완료 - 변경 {renamed}개 / 스킵 {skipped}개", flush=True)
    return jsonify({"renamed": renamed, "skipped": skipped, "errors": errors})




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
        os.remove(real)
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
                os.remove(path)
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


if __name__ == "__main__":
    config = load_config()
    port = config.get("port", 7823)
    raw = config.get("downloads_dir", "")
    resolved = resolve_downloads_dir(raw)
    print(f"서버 시작: http://localhost:{port}")
    print(f"다운로드 폴더: {resolved}")
    if not os.path.isdir(resolved):
        print("경고: 폴더가 존재하지 않습니다.")
    app.run(port=port, debug=False)
