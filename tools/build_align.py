"""
用 YouTube 字幕（.vtt，带时间轴）给每一句生成开始时间 → web/align.json
  python3 build_align.py <字幕文件夹>

- 作者上传的人工字幕：每条字幕有起止时间，句子落在字幕中间时按字数插值
- YouTube 自动字幕：每个词都有时间
- 字幕文字和 app 里的句子按词逐个比对（difflib），对上的词直接取时间，对不上的句子按前后插值
- 文件名里带视频 ID（001_xqZX3wrVFW0.es.vtt），用 transcripts.json 的 yt 字段对应集数
"""
import json, re, os, sys, glob, unicodedata, difflib, collections

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "..", "web")
SHARED = os.path.join(HERE, "..", "web_shared")

TS = r"(\d+):(\d\d):(\d\d)\.(\d\d\d)"
def ms(h, m, s, f): return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(f)

def norm(w):
    w = unicodedata.normalize("NFD", w.lower())
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", w)

def parse_vtt(path):
    """返回 [(词, 毫秒)]，以及是否是自动字幕"""
    text = open(path, encoding="utf-8").read()
    auto = "<c>" in text
    cues = []
    for block in re.split(r"\n\s*\n", text):
        m = re.search(TS + r"\s+-->\s+" + TS, block)
        if not m: continue
        a, b = ms(*m.groups()[:4]), ms(*m.groups()[4:])
        lines = block[m.end():].split("\n")[1:]
        cues.append((a, b, [l for l in lines]))
    words = []
    if auto:
        last = None
        for a, b, lines in cues:
            if b - a <= 20: continue                     # 10 毫秒的过渡字幕
            line = next((l for l in reversed(lines) if l.strip()), "")
            if not line.strip() or line == last: continue
            last = line
            if "<" not in line:                           # 整行没有词级时间（单个词）
                for w in line.split(): words.append((w, a))
                continue
            head = line.split("<", 1)[0]
            for w in head.split(): words.append((w, a))
            for mm in re.finditer(r"<(\d+:\d\d:\d\d\.\d\d\d)><c>([^<]*)</c>", line):
                t = ms(*re.match(TS, mm.group(1)).groups())
                for w in mm.group(2).split(): words.append((w, t))
    else:
        for a, b, lines in cues:
            s = " ".join(l.strip() for l in lines if l.strip())
            s = re.sub(r"<[^>]+>", "", s)
            ws = s.split()
            if not ws: continue
            total = sum(len(w) + 1 for w in ws)
            pos = 0
            for w in ws:
                words.append((w, a + int((b - a) * pos / total)))
                pos += len(w) + 1
    return [(norm(w), t) for w, t in words if norm(w)], auto

def episode_sentences(n):
    """和 app 一样的句子切分：ann/<n>.json 每段的 s 是句首 token 下标"""
    a = json.load(open(os.path.join(WEB, "ann", f"{n}.json"), encoding="utf-8"))
    sents = []
    for p in a["paras"]:
        st = p["s"] + [len(p["t"])]
        for i in range(len(p["s"])):
            sents.append([norm(t[0]) for t in p["t"][st[i]:st[i + 1]] if norm(t[0])])
    return sents

def align_episode(sents, subs, lead):
    ours, owner = [], []
    for si, ws in enumerate(sents):
        for k, w in enumerate(ws): ours.append(w); owner.append((si, k))
    sm = difflib.SequenceMatcher(None, ours, [w for w, _ in subs], autojunk=False)
    tmap = {}
    for blk in sm.get_matching_blocks():
        for d in range(blk.size): tmap[blk.a + d] = subs[blk.b + d][1]
    starts = [None] * len(sents); direct = 0
    gi = 0
    for si, ws in enumerate(sents):
        idx = list(range(gi, gi + len(ws))); gi += len(ws)
        hit = next(((j - idx[0], tmap[j]) for j in idx if j in tmap), None)
        if hit is None: continue
        k, t = hit
        if k == 0: direct += 1
        starts[si] = max(0, t - lead - k * 280)         # 句首词没对上：每个词往前估 0.28 秒
    # 保证时间单调递增，倒退的当作没对上
    best = -1
    for si in range(len(starts)):
        if starts[si] is None: continue
        if starts[si] <= best: starts[si] = None
        else: best = starts[si]
    # 没对上的句子按前后已知时间、按词数插值
    known = [i for i, x in enumerate(starts) if x is not None]
    filled = 0
    if known:
        for i in range(len(starts)):
            if starts[i] is not None: continue
            prev = max((k for k in known if k < i), default=None)
            nxt = min((k for k in known if k > i), default=None)
            if prev is not None and nxt is not None:
                wa = sum(len(sents[k]) for k in range(prev, i)); wb = sum(len(sents[k]) for k in range(prev, nxt))
                starts[i] = int(starts[prev] + (starts[nxt] - starts[prev]) * wa / max(1, wb)); filled += 1
            elif prev is not None:
                starts[i] = int(starts[prev] + 280 * sum(len(sents[k]) for k in range(prev, i))); filled += 1
            elif nxt is not None:
                starts[i] = max(0, int(starts[nxt] - 280 * sum(len(sents[k]) for k in range(i, nxt)))); filled += 1
    if starts: starts[0] = 0 if starts[0] is None or starts[0] < 1500 else starts[0]
    return starts, direct, filled, sm.ratio()

def main():
    subdir = sys.argv[1]
    eps = json.load(open(os.path.join(SHARED, "transcripts.json"), encoding="utf-8"))["episodes"]
    files = collections.defaultdict(list)
    for f in glob.glob(os.path.join(subdir, "*.vtt")):
        vid = os.path.basename(f).split("_", 1)[1].rsplit(".", 2)[0]
        files[vid].append(f)
    out, report = {}, []
    for e in eps:
        if e.get("kind") != "transcript" or not e.get("yt") or e["yt"] not in files: continue
        if not os.path.exists(os.path.join(WEB, "ann", f"{e['n']}.json")): continue
        fs = sorted(files[e["yt"]], key=lambda f: ("-ES" not in f and "es-es" not in f, f))
        subs, auto = parse_vtt(fs[0])
        sents = episode_sentences(e["n"])
        starts, direct, filled, ratio = align_episode(sents, subs, 150 if auto else 0)
        out[str(e["n"])] = starts
        report.append((e["n"], "auto" if auto else "manual", len(sents), direct, filled, round(ratio, 3)))
    json.dump(out, open(os.path.join(WEB, "align.json"), "w", encoding="utf-8"), separators=(",", ":"))
    for r in report: print(*r)
    tot = sum(r[2] for r in report); d = sum(r[3] for r in report); fl = sum(r[4] for r in report)
    print(f"episodes {len(report)}  sentences {tot}  first-word matched {d} ({d/tot:.1%})  interpolated {fl} ({fl/tot:.1%})")

if __name__ == "__main__":
    main()
