"""Print one decoded body per distinct subject from MailHog."""
import json
import quopri
import re
import sys
import urllib.request

with urllib.request.urlopen("http://localhost:8025/api/v2/messages?start=0&limit=100") as resp:
    data = json.load(resp)


def decode_subject(s):
    out = []
    for chunk in re.split(r"(=\?utf-8\?q\?[^?]+\?=)", s, flags=re.IGNORECASE):
        m = re.match(r"=\?utf-8\?q\?(.+?)\?=", chunk, re.IGNORECASE)
        if m:
            out.append(quopri.decodestring(m.group(1).replace("_", " ")).decode("utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


seen = {}
for m in data["items"]:
    subj_raw = m["Content"]["Headers"]["Subject"][0]
    subj = decode_subject(subj_raw).strip()
    bucket = subj[:50]
    if bucket in seen:
        continue
    seen[bucket] = m
    body = m["Content"]["Body"]
    enc = m["Content"]["Headers"].get("Content-Transfer-Encoding", [""])[0].lower()
    if enc == "quoted-printable":
        body = quopri.decodestring(body).decode("utf-8", errors="replace")
    print("=" * 70)
    print(f"SUBJECT: {subj}")
    print(f"TO: {m['Content']['Headers'].get('To', ['?'])[0]}")
    print("-" * 70)
    print(body)
    print()

print(f"\n{len(seen)} distinct subject buckets out of {data['total']} messages")
