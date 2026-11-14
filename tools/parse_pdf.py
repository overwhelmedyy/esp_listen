"""
把 Spanish for False Beginners 的双语 PDF 解析成结构化文本。

PDF 的排版：每页左栏西语、右栏英语，同一段的西语和英语顶端对齐。
输出：段落列表，每段 {speaker, es, en, sentences:[西语句子...]}

用法（单独测试）：python parse_pdf.py "某集.pdf"
"""
import re
import sys
import statistics
import pdfplumber

ZWSP = "​"
HEADER_RE = re.compile(r"^(Español|English|Flashcards|Spanish|Inglés)$", re.I)
SPEAKER_RE = re.compile(r"^(C|I|César|Cesar|El Inglés|Inglés|The Englishman|Englishman)\s*:\s*", re.I)
# 西语句子切分：句末标点后 + 空格 + 下一句开头（大写/¿/¡/引号）
SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])[\"”»)]?\s+(?=[¿¡«\"“(]?[A-ZÁÉÍÓÚÑÜ0-9])")


def _clean(s):
    s = s.replace(ZWSP, " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def _page_columns(page):
    """返回 (左栏行, 右栏行, 分段标记的 y 坐标)，每行 = (top, bottom, text)"""
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5)
    mid = (page.bbox[0] + page.bbox[2]) / 2
    cols = ([], [])
    seps = []
    for w in words:
        if not _clean(w["text"]):
            if ZWSP in w["text"]:
                seps.append(w["top"])   # 只有零宽空格的行 = 段落分隔
            continue
        cols[0 if w["x0"] < mid - 2 else 1].append(w)
    out = []
    for ws in cols:
        ws.sort(key=lambda w: (round(w["top"]), w["x0"]))
        lines = []
        for w in ws:
            if lines and abs(w["top"] - lines[-1]["top"]) <= 3:
                lines[-1]["words"].append(w)
                lines[-1]["bottom"] = max(lines[-1]["bottom"], w["bottom"])
            else:
                lines.append({"top": w["top"], "bottom": w["bottom"], "words": [w]})
        res = []
        for ln in lines:
            ln["words"].sort(key=lambda w: w["x0"])
            t = _clean(" ".join(w["text"] for w in ln["words"]))
            if t:
                res.append((ln["top"], ln["bottom"], t))
        out.append(res)
    return out[0], out[1], seps


def _paragraphs(lines, seps=()):
    """按行间距（和零宽空格分隔行）把一栏的行合并成段落，返回 [(top, bottom, text)]"""
    if not lines:
        return []
    gaps = [b[0] - a[0] for a, b in zip(lines, lines[1:]) if 0 < b[0] - a[0] < 40]
    step = statistics.median(gaps) if gaps else 14
    paras, cur = [], [lines[0]]
    for prev, ln in zip(lines, lines[1:]):
        sep_between = any(prev[0] + 2 < y < ln[0] - 2 for y in seps)
        if ln[0] - prev[0] > step * 1.45 or sep_between:
            paras.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    paras.append(cur)
    return [(p[0][0], p[-1][1], _clean(" ".join(l[2] for l in p))) for p in paras]


def _pair(es_paras, en_paras):
    """按垂直位置把英语段落配给西语段落。"""
    rows = [{"top": t, "bottom": b, "es": s, "en": []} for t, b, s in es_paras]
    orphans = []
    for t, b, s in en_paras:
        best, best_score = None, None
        for r in rows:
            overlap = min(b, r["bottom"]) - max(t, r["top"])
            score = overlap if overlap > 0 else -abs(t - r["top"])
            if best_score is None or score > best_score:
                best, best_score = r, score
        if best is not None and best_score > -25:
            best["en"].append((t, s))
        else:
            orphans.append((t, b, s))
    for r in rows:
        r["en"] = " ".join(s for _, s in sorted(r["en"]))
    # 只有英语没有西语的段落（少见）：作为空西语段保留，便于后面合并
    for t, b, s in orphans:
        rows.append({"top": t, "bottom": b, "es": "", "en": s})
    rows.sort(key=lambda r: r["top"])
    return rows


def split_sentences(text):
    parts = [p.strip() for p in SENT_SPLIT_RE.split(text) if p.strip()]
    # 太短的碎片（如 "Sí." 以外的单个符号）并到前一句
    out = []
    for p in parts:
        if out and len(re.sub(r"\W", "", p)) == 0:
            out[-1] += " " + p
        else:
            out.append(p)
    return out


def is_exercise_only(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        first = (pdf.pages[0].extract_text() or "")[:300]
        return len(pdf.pages) <= 2 and "Ejercicio" in first


def parse(pdf_path):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            left, right, seps = _page_columns(page)
            left = [l for l in left if not HEADER_RE.match(l[2])]
            right = [l for l in right if not HEADER_RE.match(l[2])]
            page_rows = _pair(_paragraphs(left, seps), _paragraphs(right, seps))
            if page.page_number == 1:
                # 第一页顶部横跨两栏的大标题会被切进左栏且没有英文 → 丢掉
                while page_rows and not page_rows[0]["en"] and any(r["en"] for r in page_rows):
                    page_rows.pop(0)
            rows += page_rows

    paras = []
    for r in rows:
        es, en = r["es"], r["en"]
        if not es and not en:
            continue
        if not es and paras:          # 孤立英语段 → 并入上一段
            paras[-1]["en"] = (paras[-1]["en"] + " " + en).strip()
            continue
        # 去掉段尾的 "Flashcards" 标记（标题行常带）
        es = re.sub(r"\s*Flashcards\s*$", "", es).strip()
        en = re.sub(r"\s*Flashcards\s*$", "", en).strip()
        speaker = None
        m = SPEAKER_RE.match(es)
        if m:
            speaker = m.group(1)
            es = es[m.end():]
            en = SPEAKER_RE.sub("", en, count=1)
        if not es:
            continue
        paras.append({"speaker": _norm_speaker(speaker), "es": es, "en": en})

    for p in paras:
        p["sentences"] = split_sentences(p["es"])
    return paras


def _norm_speaker(s):
    if not s:
        return None
    s = s.lower()
    if s in ("c", "césar", "cesar"):
        return "César"
    return "El Inglés"


if __name__ == "__main__":
    ps = parse(sys.argv[1])
    for i, p in enumerate(ps[:12]):
        print(f"[{i}] {p['speaker'] or ''} ES: {p['es'][:110]}")
        print(f"     EN: {p['en'][:110]}")
        print(f"     句子数: {len(p['sentences'])}")
    print("段落:", len(ps), " 句子:", sum(len(p["sentences"]) for p in ps),
          " 缺英文的段:", sum(1 for p in ps if not p["en"]))
