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

CONFIG_PATH = Path(__file__).parent / "config.json"


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
    if raw_path and len(raw_path) >= 2 and raw_path[1] == ":":
        drive = raw_path[0].lower()
        rest = raw_path[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return raw_path


import time as _time
import json as _json

_spacing_cache = {}
_cache_path = Path(__file__).parent / "spacing_cache.json"
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
COMPOUND_WORDS = [
    # 장르·캐릭터 관련
    "빌런", "천마", "마신", "마검사", "마왕", "마탄", "마탑",
    "아티팩트", "하남자", "레벨업", "방구석", "복덩이", "깡촌",

    # 등급 관련
    "역대급", "재앙급",

    # ── 현대 직장 직급 ──────────────────────────────────────────
    "인턴", "사원", "주임", "대리", "과장", "차장", "부장",
    "팀장", "실장", "본부장", "센터장", "지점장", "지사장",
    "이사", "상무", "전무", "부사장", "사장", "대표", "회장",
    "부회장", "이사장", "대표이사", "상무이사", "전무이사",
    "수석", "선임", "책임", "연구원", "연구사",

    # ── 역사·조선시대 관직 ───────────────────────────────────────
    "영의정", "좌의정", "우의정", "대감", "나리", "영감",
    "판서", "참판", "참의", "관찰사", "목사", "수령", "사또",
    "군수", "현감", "현령", "도호부사", "병마절도사",
    "대장군", "장군", "부장", "참장", "병사", "포졸",
    "상궁", "내시", "환관", "도령",

    # ── 유럽 봉건 작위 (판타지 자주 등장) ───────────────────────
    "황제", "황후", "황태자", "황태녀", "황태손",
    "대공", "공작", "후작", "백작", "자작", "남작",
    "공작부인", "백작부인", "후작부인", "남작부인",
    "왕", "왕비", "왕자", "공주", "태자", "세자",
    "영주", "기사", "귀족", "평민", "노예",
    "교황", "추기경", "대주교", "주교", "신부",
    "대사", "사절", "특사",

    # ── 판타지·무협 직업 및 색깔+직업 시리즈 ──────────────────────
    # 마법사 계열
    "마법사", "마술사", "도사", "술사", "약사", "의사",
    "흑마법사", "흑마법", "흑마도사", "흑마술사", "흑마술",
    "암흑마법사", "암흑마술사", "암흑마도사",
    "광마법사", "빙마법사", "화마법사", "독마법사", "뇌마법사",
    "대마법사", "마법왕", "마법신", "마법제",

    # 검사 계열
    "검사", "검객", "검수", "검제", "검신", "검왕",
    "흑검사", "백검사", "마검사", "신검사", "암흑검사",
    "빙검사", "화검사", "독검사", "뇌검사",
    "대검사", "검왕", "검성",

    # 기사 계열
    "기사", "성기사", "흑기사", "백기사", "적기사", "청기사",
    "용기사", "마기사", "신기사", "암흑기사", "빛기사",
    "황금기사", "철혈기사", "대기사",

    # 전사 계열
    "전사", "흑전사", "백전사", "마전사", "신전사", "암흑전사",
    "빙전사", "화전사", "독전사", "대전사", "천상전사",

    # 궁수 계열
    "궁수", "마궁수", "흑궁수", "백궁수", "신궁수",
    "빙궁수", "화궁수", "독궁수", "대궁수",

    # 무사·무인 계열
    "무사", "무인", "흑무사", "백무사", "마무사", "신무사",
    "무신", "무왕", "무제", "무성", "무림",

    # 용 계열
    "용사", "용왕", "용제", "용신", "용기사", "용검사",
    "드래곤", "용족", "반룡", "반용",

    # 악마·신 계열
    "악마", "천사", "반신", "신수", "마수", "악령",
    "귀신", "귀왕", "귀제", "귀족", "귀공자", "귀공녀",

    # 암살자·도적 계열
    "암살자", "도적", "흑암살자", "그림자검사", "그림자기사",

    # 소환·마도 계열
    "마도사", "소환사", "마도왕", "소환왕", "召唤师",

    # 독 계열
    "독술사", "독의", "독왕", "독녀", "독사",

    # MMORPG 직업
    "힐러", "탱커", "딜러", "버서커", "팔라딘",
    "위저드", "소서러", "네크로맨서", "드루이드",
    "레인저", "바드", "어쌔신", "프리스트", "몽크",

    # 무협 직급
    "협객", "방주", "장로", "문주", "총주", "교주",
    "천주", "성주", "국주", "각주", "전주", "후주",
    "도주", "단주", "부문주", "부방주", "부교주",
    "무림", "강호", "정파", "사파", "마파",

    # 귀환·각성·회귀 관련
    "헌터", "레이더", "각성자", "초월자", "회귀자",
    "환생자", "전생자", "빙의자", "귀환자", "강림자",
    "재생자", "먼치킨",

    # 폐급·등급 관련
    "폐급", "폐재", "폐인", "폐물",
    "나혼자", "고인물",

    # ── 회차·반복 관련 ─────────────────────────────────────────────
    "회차",       # N회차가 "N회 차"로 분리되는 문제 방지

    # ── 현대/연예계 ────────────────────────────────────────────────
    "아이돌", "걸그룹", "보이그룹", "아이돌그룹",
    "아이돌가수", "아이돌배우", "톱스타", "스타작가",
    "유튜버", "스트리머", "스트리밍", "브이로그",
    "연예계", "연예인", "매니저", "매니지먼트",
    "프로게이머", "게이머", "게임방송",
    "작곡가", "작사가",

    # ── 재력/신분 ──────────────────────────────────────────────────
    "재벌가", "재벌집", "재벌2세", "재벌3세",
    "억만장자", "조만장자", "만장자",
    "금수저", "은수저", "흙수저",
    "명문가", "명가",

    # ── 판타지 직업/개념 ───────────────────────────────────────────
    "플레이어", "레이더", "레이드", "게이트",
    "만렙", "뉴비", "히든", "히든클래스", "히든피스",
    "검귀", "검마", "검선", "검황", "검성",
    "마교", "이계", "선협", "차원이동",
    "정령사", "정령술사", "정령왕",
    "사령술사", "사령왕",
    "독술사", "독사",
    "시간마법사", "공간마법사",
    "얼음마법사", "불꽃마법사",

    # ── 무협 문파/지명 ─────────────────────────────────────────────
    "화산파", "소림파", "무당파", "개방파",
    "남궁", "제갈", "사천", "팽가",
    "강호", "강호인", "무림맹",

    # ── 생존/아포칼립스 ────────────────────────────────────────────
    "생존기", "생존자", "좀비바이러스", "좀비아포칼립스",
    "종말세계", "멸망세계",

    # ── 기타 자주 등장하는 복합어 ──────────────────────────────────
    "엑스트라", "조연", "보조출연",
    "데릴사위", "막내아들", "삼촌팬",
    "시한부", "회사원", "공무원", "자영업",
    "요리사", "셰프", "한의사", "대장장이",
    "먹방", "가챠", "뽑기", "짐꾼",
    "흡혈귀", "뱀파이어", "늑대인간",

    # ── 성별+직업 복합어 ────────────────────────────────────────────
    "여검사", "남검사", "여기사", "남기사", "여전사", "남전사",
    "여마법사", "남마법사", "여마도사", "남마도사", "여마술사", "남마술사",
    "여궁수", "남궁수", "여헌터", "남헌터", "여무사", "남무사",
    "여암살자", "남암살자", "여소환사", "남소환사",
    "여주", "남주", "여주인공", "남주인공",
    "여신", "여왕", "여황제", "여황", "여대공", "여공작", "여백작",
    "여사", "여사님", "여사장", "여대표", "여부장", "여과장", "여대리",
]

try:
    from kiwipiepy import Kiwi as _Kiwi
    _kiwi = _Kiwi()

    _kiwi_cache = {}

    def fix_spacing(text):
        s = text

        # 1. 복합어 재결합 (Kiwi 전, 원본에서 직접 처리)
        for word in COMPOUND_WORDS:
            if word not in s:
                for i in range(1, len(word)):
                    pat = re.escape(word[:i]) + r"\s+" + re.escape(word[i:])
                    if re.search(pat, s):
                        s = re.sub(pat, word, s)
                        break

        # 2. Kiwi 띄어쓰기 교정 (4자 이상 붙은 한글에만 적용, 결과 캐시)
        if re.search(r"[가-힣]{4,}", s):
            spaced = _kiwi_cache.get(s) or _kiwi_cache.setdefault(s, _kiwi.space(s))
            # Kiwi가 재분리한 복합어 다시 결합
            for word in COMPOUND_WORDS:
                if word in s and word not in spaced:
                    for i in range(1, len(word)):
                        pat = re.escape(word[:i]) + r"\s+" + re.escape(word[i:])
                        spaced = re.sub(pat, word, spaced)
            s = spaced

        # 3. X급 패턴
        s = re.sub(r"([A-Za-z0-9가-힣])\s+급(?![가-힣])", r"\1급", s)

        # 4. 숫자+한글
        s = re.sub(r"(?<![가-힣])(\d+)\s+([가-힣])", r"\1\2", s)

        # 5. N회차 패턴: "13회 차" → "13회차"
        s = re.sub(r"(\d+회)\s+차(?![가-힣])", r"\1차", s)

        return s

except Exception:
    def fix_spacing(text):
        return text


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
    s = stem

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
        spaced = fix_spacing(s)
        # Kiwi가 만든 단음절 연속을 다시 합치기: "헌 터" → "헌터"
        prev = None
        while prev != spaced:
            prev = spaced
            spaced = re.sub(r"(?<![가-힣])([가-힣]) ([가-힣])(?![가-힣])", r"\1\2", spaced)
        s = spaced
    # 띄어쓰기 후 재처리 - 한글이 아닌 문자로 둘러싸인 단어 치환
    s = re.sub(r"(?<![가-힣])외전(?![가-힣])", " 외 ", s)
    s = re.sub(r"(?<![가-힣])후기(?![가-힣])", " 후 ", s)
    s = re.sub(r"(?<![가-힣])포함(?![가-힣])", " ", s)
    # 한글 1~2자만 남은 빈 괄호 정리
    s = re.sub(r"[\(\[]\s*[가-힣]{0,3}\s*[\)\]]", "", s)
    s = re.sub(r" +", " ", s).strip()
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

    print(f"[이름정리] 완료 - 변경 {renamed}개 / 스킵 {skipped}개", flush=True)
    return jsonify({"renamed": renamed, "skipped": skipped, "errors": errors})




@app.route("/deduplicate-scan", methods=["GET", "POST"])
def deduplicate_scan():
    config = load_config()
    downloads_dir = resolve_downloads_dir(config.get("downloads_dir", ""))
    novel_dir = os.path.join(downloads_dir, config.get("archive_folder", "archive"))

    if not os.path.isdir(novel_dir):
        return jsonify({"error": "archive 폴더가 없습니다"}), 404

    # archive 폴더 파일 수집
    novel_files = {}
    for root, dirs, files in os.walk(novel_dir):
        for f in files:
            p = Path(f)
            stem = p.stem
            ext = p.suffix.lower()
            if stem not in novel_files:
                novel_files[stem] = {}
            novel_files[stem][ext] = os.path.join(root, f)

    # 다운로드 최상위 파일 수집
    dl_files = {}
    for f in os.listdir(downloads_dir):
        path = os.path.join(downloads_dir, f)
        if not os.path.isfile(path):
            continue
        p = Path(f)
        if p.stem not in dl_files:
            dl_files[p.stem] = {}
        dl_files[p.stem][p.suffix.lower()] = path

    items = []
    for stem, dl_exts in dl_files.items():
        if stem not in novel_files:
            continue
        novel_exts = novel_files[stem]

        for ext in dl_exts:
            if ext in novel_exts:
                items.append({
                    "delete_path": dl_exts[ext],
                    "keep_path": novel_exts[ext],
                    "delete_name": Path(dl_exts[ext]).name,
                    "keep_name": Path(novel_exts[ext]).name,
                    "delete_loc": "다운로드",
                    "keep_loc": "archive",
                    "reason": "완전 동일",
                })

        dl_epub  = ".epub" in dl_exts
        dl_txt   = ".txt"  in dl_exts
        nv_epub  = ".epub" in novel_exts
        nv_txt   = ".txt"  in novel_exts

        if dl_epub and nv_txt and ".epub" not in novel_exts:
            items.append({
                "delete_path": dl_exts[".epub"],
                "keep_path": novel_exts[".txt"],
                "delete_name": Path(dl_exts[".epub"]).name,
                "keep_name": Path(novel_exts[".txt"]).name,
                "delete_loc": "다운로드",
                "keep_loc": "archive",
                "reason": "txt 우선 (epub 삭제)",
            })

        if dl_txt and nv_epub and ".txt" not in novel_exts:
            items.append({
                "delete_path": novel_exts[".epub"],
                "keep_path": dl_exts[".txt"],
                "delete_name": Path(novel_exts[".epub"]).name,
                "keep_name": Path(dl_exts[".txt"]).name,
                "delete_loc": "archive",
                "keep_loc": "다운로드",
                "reason": "txt 우선 (epub 삭제)",
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
