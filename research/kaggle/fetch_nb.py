"""Fetch public notebook sources (anonymous) and flatten to markdown text. Usage: fetch_nb.py SLUG_SUBSTRING..."""
import json, sys, urllib.request
ks = json.load(open("kernels.json"))["kernels"]
for want in sys.argv[1:]:
    k = next((k for k in ks if want in k["scriptUrl"]), None)
    if not k:
        print("not found", want); continue
    raw = urllib.request.urlopen(f"https://www.kaggle.com/kernels/scriptcontent/{k['scriptVersionId']}/download").read()
    nb = json.loads(raw)
    out = [f"# {k['title']}", f"source: https://www.kaggle.com{k['scriptUrl']}  votes={k.get('totalVotes')} "
           f"bestPublicScore={k.get('bestPublicScore')} gpu={k.get('isGpuEnabled')} runtime_s={k.get('lastRunExecutionTimeSeconds')}", ""]
    for c in nb.get("cells", []):
        src = "".join(c.get("source", []))
        if c["cell_type"] == "markdown":
            out.append(src)
        else:
            out.append("```python\n" + src + "\n```")
            for o in c.get("outputs", [])[:2]:
                txt = "".join(o.get("text", []) or o.get("data", {}).get("text/plain", []))
                if txt.strip():
                    out.append("```\n[output] " + txt[:1500] + "\n```")
        out.append("")
    name = k["scriptUrl"].rstrip("/").split("/")[-1]
    open(f"notebooks/{name}.md", "w").write("\n".join(out))
    print(f"{name}: {len(nb.get('cells', []))} cells")
