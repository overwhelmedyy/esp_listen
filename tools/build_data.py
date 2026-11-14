"""把 transcription 文件夹里的 PDF 解析成 web/transcripts.json（app 内置数据）。
用法：python build_data.py <transcription文件夹> <对应关系.json> <输出json>
对应关系.json：[[原PDF名, 音频同名PDF名], ...]，用来取每集的 YouTube ID（音频文件名里的 [xxxx]）。
"""
import json, re, sys, glob, os
import pdfplumber
from parse_pdf import parse, is_exercise_only

src, mapping, out = sys.argv[1:4]
yt = {}
for p, n in json.load(open(mapping, encoding="utf-8")):
    m = re.search(r"\[([A-Za-z0-9_-]{11})\]\.pdf$", n)
    yt[p] = m.group(1) if m else None

# 文件名里被替换成 "_" 的字符：大多数是 "?"，下面几个特殊处理
TITLE_FIX = {
    6: '¿Qué es un "false beginner"? (or how this podcast can really help you)',
    34: "La música y el español (or Cesar´s album coming soon)",
    61: "Recuerdos de los 90 (or I´m a 90´s b*tch)",
    109: "Cuando hablas en español/francés y te responden en inglés... 🥲",
    111: "Español al desnudo: vuelta a la rutina",
    113: "Dos tácticas, dos estilos: así aprendemos idiomas",
    129: "¡Quiero el amor! España vs Inglaterra",
    139: "¡Vimos 7 pisos… y acabamos comprando ESTE!",
}

eps = []
for f in sorted(glob.glob(os.path.join(src, "*.pdf"))):
    name = os.path.basename(f)
    num = int(name[1:4])
    title = name[5:-4].strip().replace("_", "?") or ""
    title = TITLE_FIX.get(num, title)
    ep = {"n": num, "title": title, "yt": yt.get(name)}
    if is_exercise_only(f):
        with pdfplumber.open(f) as pdf:
            txt = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
        lines = [l.strip() for l in txt.replace("​", "").splitlines() if l.strip()]
        ep["kind"] = "exercise"
        ep["paras"] = [{"es": l} for l in lines]
    else:
        ep["kind"] = "transcript"
        ep["paras"] = []
        for p in parse(f):
            d = {"es": p["es"]}
            if p["en"]: d["en"] = p["en"]
            if p["speaker"]: d["s"] = p["speaker"]
            ep["paras"].append(d)
    eps.append(ep)
    print(num, ep["kind"], len(ep["paras"]), ep["yt"], file=sys.stderr)

json.dump({"version": 1, "episodes": eps}, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("episodes:", len(eps), "size:", os.path.getsize(out))
