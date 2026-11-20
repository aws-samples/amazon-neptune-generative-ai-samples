# MIT No Attribution
#
# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# SPDX-License-Identifier: MIT-0

"""
ui.py - small display helpers for the workshop notebooks (given).

    with busy("Running the validation report"):   # spinner while the cell works,
        ...                                       # then "done in 1.2 s" (or failed)
    p = progress("Bulk loading"); p.update(0.5, "detail"); p.done()   # with a meter

    show_results(rows, columns)     # a table; PASS / FAIL / BLOCKED / ok cells become pills
    show_bars(rows, title)          # labelled horizontal bars
    show_ownership(cards, title)    # small ownership graphs, coloured by what the rule blocked
    show_paths(root, paths, title)  # the paths that leave one vertex, as a tree (evidence, stock)
    show_trace(trace)               # the agent's tool calls, BLOCKED reasons highlighted
    show_reply(text, title)         # the agent's reply, in a card
    show_request(text)              # the request sent to the agent
    show_status(ok, message)        # one PASS / FAIL line
    show_code_block(text, title)    # monospace, scrollable (raw text)
    show_explain(plan_text)         # Neptune openCypher explain output as readable tables

Inside Jupyter these render as HTML; anywhere else (plain python, logs) they fall
back to readable text, so the helper modules can call them unconditionally.
"""

import html
import time
from contextlib import contextmanager

try:
    from IPython import get_ipython
    from IPython.display import HTML, display
    _IN_NOTEBOOK = get_ipython() is not None and "IPKernelApp" in get_ipython().config
except Exception:          # IPython missing, or not a kernel
    _IN_NOTEBOOK = False

_CSS = """
<style>
@keyframes guardrail-spin { to { transform: rotate(360deg); } }
.d433 { font-family: var(--jp-ui-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
        font-size: 13px; line-height: 1.45; color: var(--jp-ui-font-color1, #1f2328); }
.d433 code, .d433 pre, .d433 .mono { font-family: var(--jp-code-font-family, SFMono-Regular, Menlo, Consolas, monospace);
        font-size: 12px; }
.d433-busy { display: flex; align-items: center; gap: 8px; padding: 6px 10px; margin: 2px 0;
        border-radius: 6px; background: rgba(37, 99, 235, .08); border: 1px solid rgba(37, 99, 235, .25); }
.d433-busy.done { background: rgba(22, 163, 74, .08); border-color: rgba(22, 163, 74, .30); }
.d433-busy.fail { background: rgba(220, 38, 38, .08); border-color: rgba(220, 38, 38, .35); }
.d433-spin { width: 12px; height: 12px; border-radius: 50%; flex: none;
        border: 2px solid rgba(127, 127, 127, .35); border-top-color: #2563eb;
        animation: guardrail-spin .8s linear infinite; }
.d433-elapsed { margin-left: auto; opacity: .65; font-variant-numeric: tabular-nums; }
.d433-busy.progress { flex-wrap: wrap; }
.d433-bar { flex-basis: 100%; height: 4px; border-radius: 2px; background: rgba(127, 127, 127, .20);
        overflow: hidden; margin-top: 2px; }
.d433-bar > div { height: 100%; background: #2563eb; transition: width .6s ease; }
.d433-busy.done .d433-bar > div { background: #16a34a; }
.d433-busy.fail .d433-bar > div { background: #dc2626; }
.d433-pill { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px;
        font-weight: 600; letter-spacing: .02em; white-space: nowrap; }
.d433-pill.ok      { background: rgba(22, 163, 74, .15);  color: #15803d; }
.d433-pill.bad     { background: rgba(220, 38, 38, .15);  color: #b91c1c; }
.d433-pill.neutral { background: rgba(127, 127, 127, .15); color: inherit; }
.d433 table { border-collapse: collapse; margin: 4px 0 8px; }
.d433 th { text-align: left; font-weight: 600; padding: 4px 12px 4px 0;
        border-bottom: 1px solid rgba(127, 127, 127, .35); }
.d433 td { padding: 4px 12px 4px 0; border-bottom: 1px solid rgba(127, 127, 127, .15); vertical-align: top; }
.d433-card { border: 1px solid rgba(127, 127, 127, .30); border-radius: 8px; margin: 6px 0 10px;
        overflow: hidden; }
.d433-card > .hd { padding: 6px 12px; font-weight: 600; background: rgba(127, 127, 127, .08);
        border-bottom: 1px solid rgba(127, 127, 127, .20); }
.d433-card > .bd { padding: 8px 12px; white-space: pre-wrap; }
.d433-card.request > .hd { background: rgba(37, 99, 235, .10); }
.d433-card.reply   > .hd { background: rgba(124, 58, 237, .10); }
.d433-step { display: flex; gap: 10px; align-items: baseline; padding: 4px 0; }
.d433-step .why { margin: 2px 0 6px 0; padding: 6px 10px; border-left: 3px solid #dc2626;
        background: rgba(220, 38, 38, .06); white-space: pre-wrap; border-radius: 0 6px 6px 0; }
.d433 pre.box { max-height: 360px; overflow: auto; padding: 8px 10px; margin: 4px 0;
        white-space: pre-wrap; word-break: break-word;
        background: rgba(127, 127, 127, .07); border: 1px solid rgba(127, 127, 127, .20); border-radius: 6px; }
</style>
"""

def _wrap(body):
    # The stylesheet travels with every output: re-running or clearing an earlier
    # cell must not strip the styling from later ones.
    return HTML(_CSS + f'<div class="d433">{body}</div>')


def _html(body):
    """Display an HTML fragment; returns a handle that can be updated in place."""
    return display(_wrap(body), display_id=True)


def _esc(x):
    return html.escape("" if x is None else str(x))


_PILLS = {"PASS": "ok", "OK": "ok", "VERIFIED": "ok", "ALLOWED": "ok", "CONFORMS": "ok",
          "FAIL": "bad", "BLOCKED": "bad", "REJECTED": "bad", "ERROR": "bad"}


def pill(text):
    """A coloured badge for a status word (PASS, FAIL, BLOCKED, ok, ...)."""
    kind = _PILLS.get(str(text).strip().upper(), "neutral")
    return f'<span class="d433-pill {kind}">{_esc(text)}</span>'


@contextmanager
def busy(message):
    """Show a spinner with `message` while the block runs, then the elapsed time."""
    if not _IN_NOTEBOOK:
        print(f"... {message}", flush=True)
        try:
            yield
        except BaseException:
            print(f"FAILED: {message}", flush=True)
            raise
        print(f"done: {message}", flush=True)
        return

    handle = _html(f'<div class="d433-busy"><span class="d433-spin"></span>'
                   f'<span>{_esc(message)}</span><span class="d433-elapsed">working...</span></div>')
    try:
        yield
    except BaseException:
        handle.update(_wrap(f'<div class="d433-busy fail"><span>&#10007;</span>'
                            f'<span>{_esc(message)}</span><span class="d433-elapsed">failed</span></div>'))
        raise
    handle.update(_wrap(f'<div class="d433-busy done"><span>&#10003;</span>'
                        f'<span>{_esc(message)}</span><span class="d433-elapsed">done</span></div>'))


class progress:
    """A busy bar with a progress meter, updated in place:

        p = progress("Bulk loading the graph")
        p.update(0.4, "LOAD_IN_PROGRESS, 380,000 records")
        p.done("4,407,853 records")          # or p.fail("reason")
    """

    def __init__(self, message):
        self.message, self.t0, self.frac = message, time.perf_counter(), 0.0
        self.handle = None
        if _IN_NOTEBOOK:
            self.handle = _html(self._body("", "working..."))
        else:
            print(f"... {message}", flush=True)

    def _body(self, detail, right, state=""):
        icon = {"done": "&#10003;", "fail": "&#10007;"}.get(state, '<span class="d433-spin"></span>')
        det = f'<span style="opacity:.75">{_esc(detail)}</span>' if detail else ""
        return (f'<div class="d433-busy progress {state}">{icon}<span>{_esc(self.message)}</span>{det}'
                f'<span class="d433-elapsed">{_esc(right)}</span>'
                f'<div class="d433-bar"><div style="width:{self.frac * 100:.1f}%"></div></div></div>')

    def _show(self, detail, right, state=""):
        if self.handle is not None:
            self.handle.update(_wrap(self._body(detail, right, state)))

    def update(self, fraction=None, detail=""):
        if fraction is not None:
            self.frac = max(0.0, min(1.0, fraction))
        if self.handle is None:
            print(f"    {detail}", flush=True)
        self._show(detail, "working...")

    def done(self, detail=""):
        self.frac = 1.0
        if self.handle is None:
            print(f"done: {self.message} {detail}", flush=True)
        self._show(detail, "done", "done")

    def fail(self, detail=""):
        if self.handle is None:
            print(f"FAILED: {self.message} {detail}", flush=True)
        self._show(detail, "failed", "fail")


def show_results(rows, columns, title=None):
    """rows: list of dicts or tuples; columns: header names (dict keys if rows are dicts).
    Cells whose value is a status word render as pills."""
    def cells(r):
        return [r.get(c) for c in columns] if isinstance(r, dict) else list(r)

    if not _IN_NOTEBOOK:
        if title:
            print(title)
        widths = [max(len(str(c)), *(len(str(v)) for v in (cells(r)[i] for r in rows))) if rows
                  else len(str(c)) for i, c in enumerate(columns)]
        print("  ".join(str(c).ljust(w) for c, w in zip(columns, widths)))
        for r in rows:
            print("  ".join(str(v).ljust(w) for v, w in zip(cells(r), widths)))
        return

    def td(v):
        s = str(v)
        return f"<td>{pill(s) if s.strip().upper() in _PILLS else _esc(s)}</td>"

    head = "".join(f"<th>{_esc(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(td(v) for v in cells(r)) + "</tr>" for r in rows)
    cap = f'<div style="font-weight:600;margin-top:4px">{_esc(title)}</div>' if title else ""
    _html(f"{cap}<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")


def show_bars(rows, title=None):
    """rows: (label, value, note). One horizontal bar per row, scaled to the largest value."""
    if not _IN_NOTEBOOK:
        show_results(rows, ["", "value", ""], title)
        return
    top = max([v for _, v, _ in rows] + [1])
    bars = "".join(
        f'<tr><td style="white-space:nowrap">{_esc(label)}</td>'
        f'<td style="width:320px"><div style="height:14px;width:{max(2, 300 * v / top):.0f}px;'
        f'background:{"#dc2626" if v else "rgba(127,127,127,.35)"};border-radius:3px"></div></td>'
        f'<td style="white-space:nowrap">{_esc(note)}</td></tr>' for label, v, note in rows)
    cap = f'<div style="font-weight:600;margin-top:4px">{_esc(title)}</div>' if title else ""
    _html(f"{cap}<table><tbody>{bars}</tbody></table>")


# Graph drawings. Two layouts share one look: a layered graph (show_ownership: owners above the
# companies they own) and a tree of paths from one vertex (show_paths: a supplier on the left, one
# row per path, as the report's evidence or the stock check returns them).
_STYLES = {   # fill, border, text
    "listed":   ("#dc2626", "#991b1b", "#ffffff"),   # on a list
    "blocked":  ("#fee2e2", "#dc2626", "#991b1b"),   # blocked or flagged by a rule
    "clear":    ("#f1f5f9", "#94a3b8", "#334155"),   # nothing against it
    "supplier": ("#dbeafe", "#2563eb", "#1e3a8a"),   # where the walk starts
    "list":     ("#1f2937", "#111827", "#ffffff"),   # a sanctions or restricted list
    "warn":     ("#fef3c7", "#d97706", "#92400e"),   # a warning, or a shortfall
}
_ARROW = ('<defs><marker id="d433-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
          'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker></defs>')
_CHAR, _SUB_CHAR, _PAD = 6.8, 6.0, 14


def _lines(label, limit=22):
    """A long name on two lines, broken at the space nearest the middle."""
    if len(label) <= limit or " " not in label:
        return [label]
    spaces = [i for i, ch in enumerate(label) if ch == " "]
    cut = min(spaces, key=lambda i: abs(i - len(label) / 2))
    return [label[:cut], label[cut + 1:]]


def _box_half(label, sub=None):
    """Half the height of a vertex's box."""
    return 7 * len(_lines(label)) + 7 + (8 if sub else 0)


def _box(cx, cy, label, sub=None, style="clear", bold_border=False):
    """A vertex: a rounded box centred on (cx, cy), with an optional second line."""
    fill, stroke, ink = _STYLES[style]
    lines = _lines(label)
    w, h = _box_width(label, sub), _box_half(label, sub)
    top = cy - h + (2 * h - 14 * len(lines) - (13 if sub else 0)) / 2 + 11   # first baseline
    out = (f'<rect x="{cx - w / 2:.0f}" y="{cy - h:.0f}" width="{w:.0f}" height="{2 * h}" rx="6" fill="{fill}" '
           f'stroke="{stroke}" stroke-width="{2.5 if bold_border else 1.2}"/>' +
           "".join(f'<text x="{cx:.0f}" y="{top + 14 * k:.0f}" text-anchor="middle" fill="{ink}" '
                   f'font-weight="600">{_esc(line)}</text>' for k, line in enumerate(lines)))
    if sub:
        sub_ink = ink if style in ("listed", "list") else "#475569"
        if isinstance(sub, tuple):   # (ok, text): a check result, green or red
            sub_ink, sub = ("#15803d" if sub[0] else "#b91c1c") if sub[0] is not None else "#475569", \
                           (("✓ " if sub[0] else "✗ ") if sub[0] is not None else "") + sub[1]
        out += (f'<text x="{cx:.0f}" y="{top + 14 * (len(lines) - 1) + 16:.0f}" text-anchor="middle" font-size="11" '
                f'fill="{sub_ink}">{_esc(sub)}</text>')
    return out


def _box_width(label, sub=None):
    text = sub[1] if isinstance(sub, tuple) else sub
    return max(44, max(len(line) for line in _lines(label)) * _CHAR + 2 * _PAD,
               (len(text) + 2) * _SUB_CHAR + 2 * _PAD if text else 0)


def _edge_label(x, y, text):
    w = max(30, len(text) * 6.2 + 12)
    return (f'<rect x="{x - w / 2:.0f}" y="{y - 9:.0f}" width="{w:.0f}" height="17" rx="8" fill="#ffffff" '
            f'stroke="#cbd5e1"/><text x="{x:.0f}" y="{y + 4:.0f}" text-anchor="middle" font-size="11" '
            f'fill="#334155">{_esc(text)}</text>')


def _layered_svg(nodes, edges, min_width=250):
    """nodes: {id: {"label", "sub", "style", "bold"}}; edges: [(upper, lower, label)]. Each vertex sits
    one row below the lowest vertex with an edge into it."""
    above = {}
    for up, low, _ in edges:
        above.setdefault(low, []).append(up)
    layer = {}
    def depth(n, seen=()):
        if n not in layer:
            layer[n] = 1 + max((depth(o, seen + (n,)) for o in above.get(n, []) if o not in seen), default=-1)
        return layer[n]
    for n in nodes:
        depth(n)
    rows = {}
    for n in nodes:
        rows.setdefault(layer[n], []).append(n)
    gap, row_h = 46, 96
    width = {n: _box_width(v["label"], v.get("sub")) for n, v in nodes.items()}
    half = {n: _box_half(v["label"], v.get("sub")) for n, v in nodes.items()}
    x = {}
    for d in sorted(rows):
        if d:   # order each row under the vertices above it, to keep arrows from crossing
            rows[d].sort(key=lambda n: sum(x.get(o, 0) for o in above.get(n, [])) / max(1, len(above.get(n, []))))
        cursor = 0
        for n in rows[d]:
            x[n] = cursor + width[n] / 2
            cursor += width[n] + gap
    total = max(min_width, *(sum(width[n] for n in r) + gap * (len(r) - 1) for r in rows.values()))
    for r in rows.values():   # centre each row
        shift = (total - (sum(width[n] for n in r) + gap * (len(r) - 1))) / 2
        for n in r:
            x[n] += shift
    W, H = total + 40, 26 + row_h * (len(rows) - 1) + 34
    y = {n: 26 + row_h * layer[n] for n in nodes}
    out = [f'<svg width="{W:.0f}" height="{H:.0f}" viewBox="-20 0 {W:.0f} {H:.0f}" '
           f'xmlns="http://www.w3.org/2000/svg" style="font-family:inherit;font-size:12px">', _ARROW]
    for up, low, label in edges:
        x1, y1, x2, y2 = x[up], y[up] + half[up], x[low], y[low] - half[low] - 1
        # An edge that skips a row curves around any box it would otherwise run behind.
        mid, cy = (x1 + x2) / 2, (y1 + y2) / 2
        between = [n for n in nodes if layer[up] < layer[n] < layer[low]]
        hit = [n for n in between if abs(x[n] - (x1 + (x2 - x1) * (y[n] - y1) / (y2 - y1))) < width[n] / 2 + 12]
        if hit:
            left = min(x[n] - width[n] / 2 for n in hit) - 24
            right = max(x[n] + width[n] / 2 for n in hit) + 24
            xm = left if x1 <= (left + right) / 2 else right   # pass on the owner's side
            cx = (4 * xm - x1 - x2) / 2
        else:
            cx = mid
        out.append(f'<path d="M{x1:.0f},{y1:.0f} Q{cx:.0f},{cy:.0f} {x2:.0f},{y2:.0f}" fill="none" '
                   f'stroke="#64748b" stroke-width="1.4" marker-end="url(#d433-arrow)"/>')
        if label:
            t = 0.5 if cx == mid else 0.28   # an edge that skips a row: label it above the row it passes
            out.append(_edge_label((1 - t) ** 2 * x1 + 2 * t * (1 - t) * cx + t ** 2 * x2,
                                   (1 - t) ** 2 * y1 + 2 * t * (1 - t) * cy + t ** 2 * y2, label))
    for n, v in nodes.items():
        out.append(_box(x[n], y[n], v["label"], v.get("sub"), v.get("style", "clear"), v.get("bold")))
    out.append("</svg>")
    return "".join(out)


def _tree_svg(root, paths):
    """root: {"label", "sub", "style"}; paths: [{"tag", "tag_style", "steps": [(edge_label, vertex)]}],
    where each vertex is a dict like root. One row per path, all starting at the root. An edge label
    that starts with "<-" is drawn pointing back, for an edge stored in the other direction."""
    gap_min, row_h, tag_w = 40, 70, 0
    tag_w = max([len(p["tag"]) * 6.6 + 22 for p in paths] + [0])
    rw = _box_width(root["label"], root.get("sub"))
    rows_h = row_h * max(1, len(paths))
    H = rows_h + 16
    ry = H / 2
    out, right = [], 0
    for i, p in enumerate(paths):
        y = 8 + row_h * i + row_h / 2
        tx = rw + 46
        fill, stroke, ink = _STYLES[p.get("tag_style", "blocked")]
        out.append(f'<path d="M{rw:.0f},{ry:.0f} C{rw + 24:.0f},{ry:.0f} {tx - 24:.0f},{y:.0f} {tx:.0f},{y:.0f}" '
                   f'fill="none" stroke="#94a3b8" stroke-width="1.2"/>'
                   f'<rect x="{tx:.0f}" y="{y - 10:.0f}" width="{tag_w:.0f}" height="20" rx="10" fill="{fill}" '
                   f'stroke="{stroke}"/><text x="{tx + tag_w / 2:.0f}" y="{y + 4:.0f}" text-anchor="middle" '
                   f'font-size="11" font-weight="700" fill="{ink}">{_esc(p["tag"])}</text>')
        x = tx + tag_w
        for edge, v in p["steps"]:
            back = edge.startswith("<-")
            edge = edge[2:].strip() if back else edge
            gap = max(gap_min, len(edge) * 6.2 + 36)
            w = _box_width(v["label"], v.get("sub"))
            out.append(f'<line x1="{x + (2 if back else 0):.0f}" y1="{y:.0f}" x2="{x + gap - (0 if back else 2):.0f}" '
                       f'y2="{y:.0f}" stroke="#64748b" stroke-width="1.4" '
                       f'marker-{"start" if back else "end"}="url(#d433-arrow)"/>')
            if edge:
                out.append(_edge_label(x + gap / 2, y - 12, edge))
            out.append(_box(x + gap + w / 2, y, v["label"], v.get("sub"), v.get("style", "clear"), v.get("bold")))
            x += gap + w
        right = max(right, x)
    out.insert(0, _box(rw / 2, ry, root["label"], root.get("sub"), root.get("style", "supplier"), True))
    W = right + 12
    return (f'<svg width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" xmlns="http://www.w3.org/2000/svg" '
            f'style="font-family:inherit;font-size:12px">{_ARROW}' + "".join(out) + "</svg>")


def _legend(items, extra=""):
    keys = "".join(f'<span style="display:inline-block;width:11px;height:11px;background:{_STYLES[s][0]};'
                   f'border:1px solid {_STYLES[s][1]};border-radius:2px;margin-left:8px"></span> {_esc(t)}'
                   for s, t in items)
    return f'<div style="margin:2px 0 6px;opacity:.85">{keys} &nbsp; {_esc(extra)}</div>'


DRAWN = "Drawn from the query's rows by ui.py, the workshop's display helper, not by Neptune."


def _drawn_note(native):
    """The caption under every drawing: who drew it, and where Neptune's own view of the data is."""
    return (f'<div style="margin:2px 0 8px;font-size:11px;opacity:.7">&#9998; {_esc(DRAWN)}'
            f'{" " + _esc(native) if native else ""}</div>')


def _cards(cards, title, legend, native=None):
    body = "".join(
        f'<div class="d433-card" style="display:inline-block;vertical-align:top;margin:0 10px 10px 0">'
        f'<div class="hd">{"" if c.get("ok") is None else pill("PASS" if c["ok"] else "FAIL")} {_esc(c["title"])}'
        + (f'<div style="font-weight:400;font-size:12px;opacity:.8;max-width:280px;white-space:normal">'
           f'{_esc(c["subtitle"])}</div>' if c.get("subtitle") else "") + '</div>'
        f'<div style="padding:6px 8px;overflow-x:auto">{c["svg"]}</div></div>' for c in cards)
    cap = f'<div style="font-weight:600;margin-top:4px">{_esc(title)}</div>' if title else ""
    _html(cap + legend + f"<div>{body}</div>" + _drawn_note(native))


def show_ownership(cards, title=None, native=None):
    """cards: dicts with "title", "ok" (True, False or None for no badge), "nodes" ({name: {"blocked",
    "listed"}}), "stakes" ([(owned, owner, pct)]) and "notes" ({name: (ok, text)}, a line under the
    entities that were checked). Each card is one small ownership graph, owners above. native says
    where to see Neptune's own view of the same data, in the caption under the drawing."""
    if not _IN_NOTEBOOK:
        if title:
            print(title)
        for c in cards:
            print(("" if c.get("ok") is None else ("PASS  " if c["ok"] else "FAIL  ")) + f"{c['title']}: " +
                  "; ".join(f"{n}: {t}" for n, (_, t) in c["notes"].items()))
        return
    drawn = []
    for c in cards:
        nodes = {n: {"label": n, "sub": c["notes"].get(n), "bold": n in c["notes"],
                     "style": "listed" if v.get("listed") else "blocked" if v.get("blocked") else "clear"}
                 for n, v in c["nodes"].items()}
        drawn.append(dict(c, svg=_layered_svg(nodes, [(owner, owned, f"{pct}%") for owned, owner, pct in c["stakes"]])))
    keys = [("listed", "on the list")] + ([("blocked", "blocked by your rule")]
                                          if any(v.get("blocked") and not v.get("listed")
                                                 for c in cards for v in c["nodes"].values()) else [])
    _cards(drawn, title, _legend(keys + [("clear", "not blocked")], "arrows run from owner to owned, with the stake"),
           native)


def show_paths(root, paths, title=None, legend=None, native=None):
    """One vertex and the paths that leave it, drawn as a tree: the root on the left, one row per
    path. See _tree_svg for the shapes. Outside Jupyter, prints each path as text."""
    if not _IN_NOTEBOOK:
        if title:
            print(title)
        for p in paths:
            print(f"  [{p['tag']}] {root['label']} " + " ".join(f"-{e}-> {v['label']}" for e, v in p["steps"]))
        return
    used = {root.get("style", "supplier")} | {v.get("style", "clear") for p in paths for _, v in p["steps"]} \
        | {p.get("tag_style", "blocked") for p in paths}
    legend = [(s_, t) for s_, t in (legend or []) if s_ in used]
    cap = f'<div style="font-weight:600;margin-top:4px">{_esc(title)}</div>' if title else ""
    _html(cap + (_legend(legend) if legend else "") +
          f'<div class="d433-card" style="display:inline-block;padding:8px 10px;overflow-x:auto;margin-bottom:0">'
          f'{_tree_svg(root, paths)}</div>' + _drawn_note(native))


def show_status(ok, message):
    """One PASS / FAIL line."""
    if not _IN_NOTEBOOK:
        print(f"{'PASS' if ok else 'FAIL'}  {message}")
        return
    _html(f'<div style="margin:4px 0">{pill("PASS" if ok else "FAIL")} {_esc(message)}</div>')


def show_note(message):
    """One informational line, no PASS or FAIL: what ran, or a value to read."""
    if not _IN_NOTEBOOK:
        print(f"note  {message}")
        return
    _html(f'<div style="margin:4px 0;opacity:.85">&#9432; {_esc(message)}</div>')


def _card(kind, title, text):
    if not _IN_NOTEBOOK:
        print(f"--- {title} ---\n{text}\n")
        return
    _html(f'<div class="d433-card {kind}"><div class="hd">{_esc(title)}</div>'
          f'<div class="bd">{_esc(text)}</div></div>')


def show_request(text, title="Request"):
    _card("request", title, text)


def show_reply(text, title="Agent reply"):
    _card("reply", title, text)


def show_code_block(text, title=None, wrap=True):
    """Monospace, scrollable block for raw text. wrap=False keeps wide ASCII
    tables intact (scroll sideways instead of wrapping)."""
    if not _IN_NOTEBOOK:
        if title:
            print(title)
        print(text)
        return
    cap = f'<div style="font-weight:600;margin-top:4px">{_esc(title)}</div>' if title else ""
    style = "" if wrap else ' style="white-space:pre;word-break:normal"'
    _html(f'{cap}<pre class="box"{style}>{_esc(text)}</pre>')


# ── Neptune openCypher explain ────────────────────────────────────────────────
# Neptune returns the plan as box-drawn ASCII tables: a "Query:" header, then one
# table per (sub)query, each preceded by its name. Rows can span several lines
# (continuation lines have an empty ID cell). parse_explain() turns that into
# [{"title", "columns", "rows"}]; show_explain() renders it as HTML tables.

_BOX = "╔║╠╟╚"


def parse_explain(text):
    """Parse Neptune openCypher explain text. Returns (query, tables)."""
    query_lines, tables, title, cur, in_query = [], [], None, None, False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        ch = line[0]
        if ch not in _BOX:
            if line.strip() == "Query:":
                in_query = True
            elif in_query and not tables and cur is None:
                query_lines.append(line)
            else:
                title = line.strip()
            continue
        in_query = False
        if ch == "╔":
            cur = {"title": title or "Plan", "columns": None, "rows": []}
            tables.append(cur)
            title = None
        elif ch == "║" and cur is not None:
            cells = [c.strip() for c in line.strip("║").split("│")]
            if cur["columns"] is None:
                cur["columns"] = cells
            elif cells[0] == "" and cur["rows"]:
                prev = cur["rows"][-1]
                for i, c in enumerate(cells):
                    if c:
                        prev[i] = (prev[i] + "\n" + c) if prev[i] else c
            else:
                cur["rows"].append(cells)
        elif ch == "╚":
            cur = None
    if not tables or any(t["columns"] is None for t in tables):
        raise ValueError("not a Neptune explain table")
    return "\n".join(query_lines).strip(), tables


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _op_kind(name):
    n = name.replace("DFE", "")
    if n in ("PipelineScan", "PipelineJoin", "PipelineRangeScan"):
        return "scan"
    if "Join" in n or n in ("HashIndexBuild", "Tee", "Sync"):
        return "join"
    if "Filter" in n or "Distinct" in n or "Limit" in n or "OrderBy" in n or "Sort" in n:
        return "filter"
    if "SubQuery" in n or "Subquery" in n or n in ("Optional", "Union", "LoopSubQuery"):
        return "sub"
    if n in ("SolutionInjection", "Drain", "ForwardValue", "Project", "TermResolution",
             "ReduceDataType", "ForwardValue"):
        return "plumbing"
    return "other"


_OP_STYLE = {"scan": "background:rgba(37,99,235,.14);color:#1d4ed8",
             "join": "background:rgba(124,58,237,.14);color:#6d28d9",
             "filter": "background:rgba(217,119,6,.16);color:#b45309",
             "sub": "background:rgba(13,148,136,.14);color:#0f766e",
             "plumbing": "background:rgba(127,127,127,.12);opacity:.75",
             "other": "background:rgba(127,127,127,.12)"}


def _table_title(t):
    s = t
    if s.startswith("subQuery=") and "/" in s:
        s = "Chunk subquery " + s.rsplit("/", 1)[-1]
    elif s.startswith("subQuery"):
        s = "Subquery " + s[len("subQuery"):]
    return s


def show_explain(text, title="Neptune query plan"):
    """Render Neptune openCypher explain output as readable tables, with a
    summary of where the plan starts. Falls back to the raw text if the
    format is not recognised."""
    try:
        query, tables = parse_explain(text)
    except Exception:
        show_code_block(text, title, wrap=False)
        return
    if not _IN_NOTEBOOK:
        print(title)
        for t in tables:
            print(f"\n{_table_title(t['title'])}")
            for r in t["rows"]:
                print("  " + " | ".join(c.replace(chr(10), "; ") for c in r))
        return

    # Summary: the first scans (where the engine starts reading the graph) and
    # the operator that produced the most rows.
    scans, busiest = [], None
    for t in tables:
        cols = t["columns"]
        ix = {c: i for i, c in enumerate(cols)}
        for r in t["rows"]:
            name = r[ix.get("Name", 3)]
            args = r[ix.get("Arguments", 4)] if "Arguments" in ix else ""
            if _op_kind(name) == "scan":
                pat = next((a for a in args.split("\n") if a.startswith("pattern=")), args.split("\n")[0])
                est = next((a.split("=", 1)[1] for a in args.split("\n") if a.startswith("patternEstimate=")), "?")
                scans.append((name.replace("DFE", ""), pat[len("pattern="):] if pat.startswith("pattern=") else pat, est))
            out = _num(r[ix["Units Out"]]) if "Units Out" in ix else 0
            if busiest is None or out > busiest[1]:
                busiest = (name.replace("DFE", ""), out, _table_title(t["title"]))
    summary = ""
    if scans:
        name, pat, est = scans[0]
        summary += (f'<div style="margin:4px 0"><b>Starts from:</b> <span class="mono">{_esc(pat)}</span> '
                    f'<span style="opacity:.7">({_esc(name)}, estimate {_esc(est)})</span></div>')
        if len(scans) > 1:
            items = "".join(f'<li><span class="mono">{_esc(p)}</span> '
                            f'<span style="opacity:.7">(estimate {_esc(e)})</span></li>' for _, p, e in scans[1:])
            summary += f'<div style="margin:2px 0"><b>Then reads:</b><ol style="margin:2px 0 4px 18px;padding:0">{items}</ol></div>'
    if busiest and busiest[1] > 0:
        summary += (f'<div style="margin:2px 0"><b>Most rows produced:</b> {_esc(busiest[0])} '
                    f'({busiest[1]:,.0f}, in {_esc(busiest[2])})</div>')

    parts = [f'<div style="font-weight:700;font-size:14px;margin:6px 0 2px">{_esc(title)}</div>', summary]
    if query:
        parts.append(f'<details style="margin:4px 0"><summary>Query</summary>'
                     f'<pre class="box" style="white-space:pre">{_esc(query)}</pre></details>')
    for t in tables:
        cols, rows = t["columns"], t["rows"]
        # Hide columns that carry nothing in this table (all '-', empty, or zero).
        keep = [i for i, c in enumerate(cols)
                if c in ("ID", "Name") or any(r[i] not in ("", "-", "0", "0.00") for r in rows)]
        head = "".join(f"<th>{_esc(cols[i])}</th>" for i in keep)
        body = []
        for r in rows:
            tds = []
            for i in keep:
                c, v = cols[i], r[i]
                if c == "Name":
                    tds.append(f'<td><span class="d433-pill" style="{_OP_STYLE[_op_kind(v)]}">'
                               f'{_esc(v.replace("DFE", ""))}</span></td>')
                elif c == "Arguments":
                    lines = "".join(f"<div>{_esc(a)}</div>" for a in v.split("\n") if a and a != "-")
                    tds.append(f'<td class="mono" style="max-width:640px;word-break:break-word">{lines or "-"}</td>')
                elif c in ("Units In", "Units Out", "Ratio", "Time (ms)", "ID", "Out #1", "Out #2"):
                    tds.append(f'<td class="mono" style="text-align:right">{_esc(v)}</td>')
                else:
                    tds.append(f"<td>{_esc(v)}</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        parts.append(f'<div style="font-weight:600;margin:10px 0 2px">{_esc(_table_title(t["title"]))}</div>'
                     f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>')
    legend = " ".join(f'<span class="d433-pill" style="{_OP_STYLE[k]}">{lbl}</span>' for k, lbl in
                      [("scan", "reads the graph"), ("join", "joins"), ("filter", "filters / sorts"),
                       ("sub", "subquery"), ("plumbing", "bookkeeping")])
    parts.append(f'<div style="margin:6px 0;opacity:.85">{legend}</div>')
    _html("".join(parts))


def show_trace(trace, title="What the agent did"):
    """The tool calls from a run, one row each; BLOCKED rows show the guard's reasons."""
    if not _IN_NOTEBOOK:
        print(title)
        for t in trace:
            args = ", ".join(f"{k}={v!r}" for k, v in t.get("input", {}).items() if k != "message")
            print(f"  [{t.get('outcome', '?'):<7}] {t.get('tool')}({args})")
            if t.get("outcome") != "ok":
                for line in t.get("output", "").splitlines():
                    print(f"             {line}")
        return
    if not trace:
        _html(f'<div style="margin:4px 0">{pill("no tool calls")} '
              f'<span style="opacity:.75">the agent answered without acting</span></div>')
        return
    rows = []
    for t in trace:
        args = ", ".join(f"{_esc(k)}=<b>{_esc(v)}</b>" for k, v in t.get("input", {}).items()
                         if k != "message")
        why = ""
        if t.get("outcome") != "ok":
            why = f'<div class="why mono">{_esc(t.get("output", ""))}</div>'
        rows.append(f'<div class="d433-step"><div>{pill(t.get("outcome", "?"))}</div>'
                    f'<div style="flex:1"><span class="mono">{_esc(t.get("tool"))}</span>'
                    f'<span class="mono" style="opacity:.8">({args})</span>{why}</div></div>')
    _html(f'<div style="font-weight:600;margin:6px 0 2px">{_esc(title)}</div>' + "".join(rows))


def banner(title, subtitle=None):
    """A section header inside a long-running loop (one per scenario)."""
    if not _IN_NOTEBOOK:
        print("=" * 100 + f"\n{title}" + (f"\n{subtitle}" if subtitle else "") + "\n" + "=" * 100)
        return
    sub = f'<div style="opacity:.7">{_esc(subtitle)}</div>' if subtitle else ""
    _html(f'<div style="margin:14px 0 4px;padding:6px 0;border-top:2px solid rgba(127,127,127,.35)">'
          f'<div style="font-size:14px;font-weight:700">{_esc(title)}</div>{sub}</div>')
