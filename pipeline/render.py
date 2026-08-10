"""
render.py — Iran War Update, HTML email render (Phase 4a)

Converts the Markdown brief from digest.py into a clean, Outlook-friendly HTML email that
mirrors the tracker's look: bold category headers, bulleted items, indented sub-bullets,
source links on the verb. Stdlib only (a small purpose-built Markdown subset converter,
so there are no dependencies and no surprises in how email clients render it).
"""

import re
import sys
from pathlib import Path

OUT_DIR = Path(__file__).parent / "out"


def _inline(text):
    """Handle inline: [text](url), **bold**, `code`, and escape stray < >."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                  r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r'<code style="color:#a33;">\1</code>', text)
    return text


def md_to_html(md):
    lines = md.splitlines()
    html, in_list = [], False

    def close_list():
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            close_list()
            continue
        # sub-bullet (indented "- " or "  * ")
        m_sub = re.match(r"^(?:\s{2,}|\t)[-*]\s+(.*)", raw)
        m_top = re.match(r"^[-*]\s+(.*)", line)
        is_header = line.startswith("**") and line.endswith("**") and "](" not in line
        if is_header:
            close_list()
            html.append(f'<p style="margin:14px 0 4px;font-weight:bold;">'
                        f'{_inline(line.strip("*"))}</p>')
        elif m_sub:
            if not in_list:
                html.append("<ul style='margin:2px 0;'>")
                in_list = True
            html.append(f'<li style="margin-left:22px;list-style:circle;">'
                        f'{_inline(m_sub.group(1))}</li>')
        elif m_top:
            if not in_list:
                html.append("<ul style='margin:2px 0;'>")
                in_list = True
            html.append(f"<li style='margin:3px 0;'>{_inline(m_top.group(1))}</li>")
        else:
            close_list()
            html.append(f"<p>{_inline(line)}</p>")
    close_list()

    body = "\n".join(html)
    return f"""<!DOCTYPE html>
<html><body style="font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#111;line-height:1.4;">
<p style="color:#888;font-size:9pt;">Auto-drafted by the Iran War Update pipeline. Review before sending.</p>
{body}
</body></html>"""


def render(md_path=None):
    if md_path is None:
        briefs = sorted(OUT_DIR.glob("brief_*.md"))
        if not briefs:
            sys.exit("No brief_*.md found. Run digest.py first.")
        md_path = briefs[-1]
    md_path = Path(md_path)
    html = md_to_html(md_path.read_text(encoding="utf-8"))
    html_path = md_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    print(f"Wrote {html_path}")
    return html_path


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else None)
