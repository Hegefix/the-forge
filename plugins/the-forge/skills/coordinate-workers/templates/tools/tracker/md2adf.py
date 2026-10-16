#!/usr/bin/env python3
"""md2adf: Markdown to Atlassian Document Format (ADF), with real task checkboxes.

A tracker that stores rich text as ADF (Jira, Confluence) shows `- [ ] item` sent as Markdown as plain
text. This turns it into a real `taskList`, which people can tick and which an agent can tick after merge
(acceptance criteria, technical requirements). Send the output as the ADF body of a description or a
comment through the tracker's API or MCP tool.

Handles: `#`–`######` headings, paragraphs (one per line), `-`/`*` bullet lists, `- [ ]`/`- [x]` task
lists, and `inline code`. Backslash escapes such as `\\[` are removed. Anything else (bold, links,
numbered or nested lists, tables) stays plain text.

Usage: md2adf.py <file.md | ->   prints the ADF document as JSON
"""
import json, re, sys, uuid

ESC = re.compile(r'\\([\[\]\\*_`#>!-])')
TASK = re.compile(r'^[*-] \\?\[( |x|X)\\?\] ')
BUL = re.compile(r'^[*-] ')


def inline(text):
    out = []
    pos = 0
    for m in re.finditer(r'`([^`]+)`', text):
        if m.start() > pos:
            out.append({"type": "text", "text": ESC.sub(r'\1', text[pos:m.start()])})
        out.append({"type": "text", "text": m.group(1), "marks": [{"type": "code"}]})
        pos = m.end()
    if pos < len(text):
        out.append({"type": "text", "text": ESC.sub(r'\1', text[pos:])})
    return [n for n in out if n["text"]]


def convert(md):
    doc = {"type": "doc", "version": 1, "content": []}
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = re.match(r'^(#{1,6}) (.*)', line)
        if m:
            doc["content"].append({"type": "heading", "attrs": {"level": len(m.group(1))}, "content": inline(m.group(2))})
            i += 1
            continue
        if TASK.match(line):
            items = []
            while i < len(lines) and TASK.match(lines[i]):
                mm = TASK.match(lines[i])
                items.append({"type": "taskItem",
                              "attrs": {"localId": str(uuid.uuid4()), "state": "TODO" if mm.group(1) == " " else "DONE"},
                              "content": inline(lines[i][mm.end():])})
                i += 1
            doc["content"].append({"type": "taskList", "attrs": {"localId": str(uuid.uuid4())}, "content": items})
            continue
        if BUL.match(line):
            items = []
            while i < len(lines) and BUL.match(lines[i]) and not TASK.match(lines[i]):
                items.append({"type": "listItem", "content": [{"type": "paragraph", "content": inline(lines[i][2:])}]})
                i += 1
            doc["content"].append({"type": "bulletList", "content": items})
            continue
        doc["content"].append({"type": "paragraph", "content": inline(line)})
        i += 1
    return doc


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    text = sys.stdin.read() if sys.argv[1] == "-" else open(sys.argv[1]).read()
    print(json.dumps(convert(text), ensure_ascii=False))
