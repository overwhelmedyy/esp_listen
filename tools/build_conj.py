"""用 verbecc（LGPL-3，https://github.com/bretttolbert/verbecc）为文本里出现的所有动词生成变位表 web/conj.json。
只存简单时态；复合时态（haber + 过去分词）在界面里由 haber 的变位拼出来。"""
import json, os, sys, logging
logging.disable(logging.CRITICAL)
from verbecc import CompleteConjugator

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")
PERS = ["yo", "tú", "él", "nosotros", "vosotros", "ellos"]
IMP_PERS = ["tú", "usted", "nosotros", "vosotros", "ustedes"]
KEYS = {  # 我们的键 → (mood, tense)
    "ip": ("indicativo", "presente"), "is": ("indicativo", "pretérito-perfecto-simple"),
    "ii": ("indicativo", "pretérito-imperfecto"), "if": ("indicativo", "futuro"),
    "cp": ("condicional", "presente"), "sp": ("subjuntivo", "presente"),
    "si": ("subjuntivo", "pretérito-imperfecto-1"), "si2": ("subjuntivo", "pretérito-imperfecto-2"),
}

ANALOG = {   # 动词: (同规律的模板动词, [(模板词干, 新词干), ...])
    "pasar": ("cortar", [("cort", "pas")]),
    "nevar": ("cerrar", [("cierr", "niev"), ("cerr", "nev")]),
    "helar": ("cerrar", [("cierr", "hiel"), ("cerr", "hel")]),
}
FORCE = {   # verbecc 猜错模板的动词：直接用正确的模板动词替换词干
    "atrever": ("temer", [("tem", "atrev")]),
    "complacer": ("nacer", [("nac", "complac"), ("naz", "complaz")]),
}
# 真正的不规则过去分词；verbecc 给出的其它非 -ado/-ido 形式（electo, nato, correcto…）是形容词，复合时态要用规则分词
IRREG_PP = set("""abierto cubierto descubierto dicho contradicho predicho escrito descrito inscrito suscrito
hecho muerto puesto expuesto impuesto propuesto supuesto resuelto roto visto vuelto devuelto frito impreso""".split())
def regular_pp(v):
    b = v[:-2]
    if v.endswith("ar"): return b + "ado"
    return b + ("ído" if b.endswith(("a", "e", "o")) else "ido")

def strip(entry):
    form = entry["c"][0]
    pr = entry.get("pr")
    if pr and form.startswith(pr + " "): form = form[len(pr) + 1:]
    return " / ".join(c[len(pr) + 1:] if pr and c.startswith(pr + " ") else c for c in entry["c"]) if len(entry["c"]) > 1 else form

def conj_one(cg, v):
    base = v[:-2] if v.endswith("se") and len(v) > 4 and v[:-2].endswith(("ar", "er", "ir", "ír")) else v
    try:
        if base in FORCE: raise KeyError(base)
        r = json.loads(str(cg.conjugate(base)))
    except Exception:
        # verbecc 对个别动词会报错：用变位规律相同的动词替换词干得到
        if base in FORCE or base in ANALOG:
            model, pairs = FORCE.get(base) or ANALOG[base]
        elif base.endswith(("ar", "er", "ir")) and len(base) > 3:
            # verbecc 内部出错的规则动词：按规则变位模板替换词干
            model = {"ar": "cortar", "er": "temer", "ir": "vivir"}[base[-2:]]
            pairs = [(model[:-2], base[:-2])]
        else:
            return base, None
        txt = str(cg.conjugate(model))
        for a, b in pairs: txt = txt.replace(a, b)
        r = json.loads(txt)
    m = r["moods"]
    d = {"f": {}}
    for k, (mood, tense) in KEYS.items():
        rows = {e.get("pr"): strip(e) for e in m.get(mood, {}).get(tense, [])}
        d["f"][k] = [rows.get(p, "") for p in PERS]
    for k, tense in (("ia", "afirmativo"), ("in", "negativo")):
        rows = {e.get("pr"): strip(e) for e in m.get("imperativo", {}).get(tense, [])}
        d["f"][k] = [rows.get(p, "") for p in IMP_PERS]
    d["g"] = strip(m["gerundio"]["gerundio"][0]) if m.get("gerundio") else ""
    d["pp"] = strip(m["participo"]["participo"][0]) if m.get("participo") else ""
    if d["pp"] and not d["pp"].endswith(("ado", "ido", "ído")) and d["pp"] not in IRREG_PP:
        d["pp"] = regular_pp(base)
    if base == "haber":
        d["f"]["ip"][2] = "ha"          # hay 只用于无人称“有”
        d["f"]["ia"][0] = "he"
    if base == "valer": d["f"]["ia"][0] = "vale"
    for root, imp in (("tener", "tén"), ("poner", "pón"), ("venir", "vén")):   # 复合动词的 tú 命令式带重音：mantén, propón, prevén
        if base.endswith(root) and base != root:
            d["f"]["ia"][0] = base[:-len(root)] + imp
    if base.endswith("reír"):           # 单音节不加重音（RAE 2010）：riais
        d["f"]["sp"] = [f.replace("riáis", "riais") for f in d["f"]["sp"]]
        d["f"]["in"] = [f.replace("riáis", "riais") for f in d["f"]["in"]]
    if r["verb"].get("predicted") and base not in FORCE: d["pred"] = 1
    d["tpl"] = r["verb"].get("template", "").replace(":", "")
    return base, d

def main():
    lex = json.load(open(os.path.join(WEB, "lex.json"), encoding="utf-8"))
    verbs = sorted({e["w"] for e in lex if e["p"] == "verb"} | {"haber"})
    cg = CompleteConjugator(lang="es")
    out, bad = {}, []
    for v in verbs:
        base, d = conj_one(cg, v)
        if d is None: bad.append(v); continue
        out[base] = d
    json.dump(out, open(os.path.join(WEB, "conj.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("verbs:", len(out), "predicted:", sum(1 for x in out.values() if x.get("pred")), "failed:", bad[:20])

if __name__ == "__main__":
    main()
