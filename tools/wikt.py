"""解析 doozan/spanish_data 的 es-en.data → {headword: [{pos, glosses:[...], g:gender}]}"""
import re, json
def load(path="/tmp/sd/es-en.data"):
    d = {}
    word = None; cur = None
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line == "_____":
            word = None; continue
        if word is None:
            word = line; d.setdefault(word, []); continue
        if line.startswith("pos: "):
            cur = {"pos": line[5:], "glosses": []}; d[word].append(cur); continue
        s = line.strip()
        if cur is None: continue
        if s.startswith("gloss: "):
            cur["glosses"].append(s[7:]); cur.setdefault("q", []).append("")
        elif s.startswith("q: ") and cur.get("glosses"):
            cur["q"][-1] = (cur["q"][-1] + "; " + s[3:]).strip("; ")
        elif s.startswith("g: ") and line.startswith("  g:"):
            cur["g"] = s[3:]
    return d
if __name__ == "__main__":
    d = load()
    json.dump(d, open("wikt.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(len(d), sum(1 for k in d if " " in k))
    for k in ["casa", "darse cuenta", "echar de menos", "a lo mejor", "sin embargo", "tener", "pues"]:
        print(k, json.dumps(d.get(k), ensure_ascii=False)[:300])
