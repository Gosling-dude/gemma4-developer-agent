"""Dump a Kaggle discussion topic (first post + comments + replies) to markdown. Usage: dump_topic.py ID"""
import json, subprocess, sys
tid = sys.argv[1]
raw = subprocess.run(["./kapi.sh", "discussions.DiscussionsService/GetForumTopicById",
                      json.dumps({"forumTopicId": int(tid), "includeComments": True})], capture_output=True, text=True).stdout
t = json.loads(raw)["forumTopic"]
out = [f"# {t.get('name') or t.get('title')}  (topic {tid})", ""]
fm = t.get("firstMessage") or {}
out += [f"**{t.get('authorUserDisplayName')}** ({fm.get('postDate','')})", "", fm.get("rawMarkdown") or fm.get("content") or "", ""]
def walk(cs, depth):
    for c in cs or []:
        who = c.get("author", {}).get("displayName") or c.get("authorUserDisplayName") or "?"
        typ = c.get("authorType") or c.get("author", {}).get("type", "")
        out.append(f"{'>' * depth} **{who}** {typ} ({c.get('postDate','')[:10]}): " + (c.get("rawMarkdown") or "").replace("\n", "\n" + ">" * depth + " "))
        out.append("")
        walk(c.get("replies"), depth + 1)
walk(t.get("comments"), 1)
open(f"discussion/{tid}.md", "w").write("\n".join(out))
print(f"{tid}: {len(out)} lines")
