#!/usr/bin/env python3
"""检查文档交叉引用：文件是否存在、§章节号是否存在。

用法：python tools/check_refs.py <目录>
"""
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
md = [p for p in root.rglob("*.md")]
files = {str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file()}

sections = {}
for p in md:
    rel = str(p.relative_to(root)).replace("\\", "/")
    text = p.read_text(encoding="utf-8")
    sections[rel] = set(re.findall(r"^#{1,4}\s*(\d+(?:\.\d+)?)[.\s]", text, re.M))

bad = []
for p in md:
    rel = str(p.relative_to(root)).replace("\\", "/")
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        for m in re.finditer(r"(?:references|templates)/[\w\u4e00-\u9fa5.-]+\.md", line):
            if m.group(0) not in files:
                bad.append(f"{rel}:{i} 文件不存在 {m.group(0)}")
        # 相对链接：](xxx.md) 必须相对于本文件存在
        for m in re.finditer(r"\\]\\(([\\w\\u4e00-\\u9fa5./-]+\\.md)\\)", line):
            if not (p.parent / m.group(1)).resolve().exists():
                bad.append(f"{rel}:{i} 相对链接不存在 {m.group(1)}")
        rest = line
        for m in re.finditer(r"([\w\u4e00-\u9fa5.-]+\.md)\s*§(\d+(?:\.\d+)?)", line):
            target = next((k for k in sections if k == m.group(1) or k.endswith("/" + m.group(1))), None)
            if target and m.group(2) not in sections[target]:
                bad.append(f"{rel}:{i} {m.group(1)} 无 §{m.group(2)}")
            rest = rest.replace(m.group(0), "")

if bad:
    print(f"发现 {len(bad)} 处断链：")
    for b in bad:
        print("  " + b)
    sys.exit(1)
print("交叉引用检查通过。")
