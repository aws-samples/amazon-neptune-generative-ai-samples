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
"""lineage_view.py — Cell 3.3's drawing: the walk's sampled decisions and every node on their typed
paths back to the model version, laid out one column per hop (the mockup's layout), as an SVG.

The layout: each node's column is its BFS hop from the source over both routes; a decision sits in
its own column right of its hop's artifacts, and a notice at its own hop. Within a column, the order
comes from a depth-first walk from the source, then barycenter sweeps; heights are pulled toward each
node's neighbors while keeping the order and the spacing (pool-adjacent-violators), so a chain of
refreshed records runs straight and an artifact many decisions share sits among them. A column with
many nodes staggers them in two lanes."""
import html
import json
import uuid
from collections import deque

R = 9                      # node radius
GAP, PITCH, PITCH_DENSE, STAGGER, DENSE = 64, 30, 21, 13, 9
KIND_ORDER = ["version", "extraction", "employer_record", "business_income", "income", "ratios", "decision", "notice"]
COLORS = {"version": "#5b3cc4", "extraction": "#c3c2b7", "employer_record": "#9ec5f4", "income": "#e3e1da",
          "ratios": "#e3e1da", "business_income": "#e3e1da", "notice": "#6b3a2e",
          "approve": "#0ca30c", "deny": "#d03b3b", "escalate": "#fab219"}
RING = "#5b3cc4"


def layout(nodes, edges, source):
    """nodes: {id: {"kind", ...}}; edges: [(from, to, label)] pointing upstream (toward the source).
    Sets each node's "level", "x" and "y"; returns the column keys and their x."""
    into = {n: [] for n in nodes}                     # downstream: who points at me
    for a, b, _ in edges:
        if a in nodes and b in nodes:
            into[b].append(a)
    level = {source: 0}
    q = deque([source])
    while q:
        v = q.popleft()
        for u in into[v]:
            if u not in level:
                level[u] = level[v] + 1
                q.append(u)
    walk = [n for n in nodes if n in level]
    for n in walk:
        nodes[n]["level"] = level[n]
    is_dec = lambda n: nodes[n]["kind"] == "decision"
    key = lambda n: level[n] * 2 + (1 if is_dec(n) else 0)
    cols = {}
    for n in walk:
        cols.setdefault(key(n), []).append(n)
    keys = sorted(cols)
    nb = {n: set() for n in walk}
    for a, b, _ in edges:
        if a in level and b in level and a != b:
            nb[a].add(b)
            nb[b].add(a)
    rank = lambda n: (key(n), KIND_ORDER.index(nodes[n]["kind"]) if nodes[n]["kind"] in KIND_ORDER else 9, n)
    dfs, seen = {}, set()

    def visit(n):
        stack = [n]
        while stack:
            v = stack.pop()
            if v in seen:
                continue
            seen.add(v)
            dfs[v] = len(dfs)
            stack.extend(sorted(into[v], key=rank, reverse=True))
    visit(source)
    for n in sorted(walk, key=rank):
        visit(n)
    order = {k: sorted(cols[k], key=dfs.get) for k in keys}
    lanes = {k: 2 if len(order[k]) > DENSE and k % 2 == 0 else 1 for k in keys}
    pitch = lambda k: PITCH_DENSE if lanes[k] == 2 else PITCH
    ys = {}

    def place(k):
        lst, p = order[k], pitch(k)
        for i, n in enumerate(lst):
            ys[n] = (i - (len(lst) - 1) / 2) * p
    for k in keys:
        place(k)
    for _ in range(6):
        for direction in (1, -1):
            ks = keys[1:] if direction > 0 else list(reversed(keys[:-1]))
            for k in ks:
                def bary(n):
                    v = [ys[m] for m in nb[n] if (key(m) < k if direction > 0 else key(m) > k)]
                    return sum(v) / len(v) if v else ys[n]
                b = {n: bary(n) for n in order[k]}
                order[k].sort(key=lambda n: (b[n], dfs[n]))
                place(k)

    def pav(want, p):
        blocks = []
        for i, w in enumerate(want):
            blocks.append([w - i * p, 1])
            while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
                s, c = blocks.pop()
                blocks[-1][0] += s
                blocks[-1][1] += c
        out = []
        for s, c in blocks:
            out += [s / c + (len(out) + j) * p for j in range(c)]
        return out
    for _ in range(24):
        for k in keys:
            lst = order[k]
            mean = lambda n: (sum(ys[m] for m in nb[n]) / len(nb[n])) if nb[n] else ys[n]
            want = [0.4 * ys[n] + 0.6 * mean(n) for n in lst]
            for n, y in zip(lst, pav(want, pitch(k))):
                ys[n] = y
    xs, x, prev = {}, 0, None
    for k in keys:
        if prev is not None:
            half = lambda kk: (lanes[kk] - 1) / 2 * 2 * STAGGER
            need = 2 * R + 6 + half(prev) + half(k)
            x += max(need + 14 if k % 2 else GAP, need)
        xs[k] = x
        prev = k
    y0 = ys.get(source, 0)
    for k in keys:
        for i, n in enumerate(order[k]):
            off = ((i % 2) - 0.5) * 2 * STAGGER if lanes[k] == 2 else 0
            nodes[n]["x"], nodes[n]["y"] = xs[k] + off, ys[n] - y0
    return keys, xs, key


WALKS = {   # Cell 3.2's three walks: the edge labels each follows, inbound from the version
    "both": ("Trace the query", ["PRODUCED_BY", "DERIVED_FROM", "IDENTITY_FROM", "USED", "RESTS_ON"]),
    "amounts": ("amounts", ["PRODUCED_BY", "DERIVED_FROM", "USED", "RESTS_ON"]),
    "identities": ("identities", ["PRODUCED_BY", "IDENTITY_FROM", "USED", "RESTS_ON"]),
}
STEP = 0.7     # seconds per hop in the trace

TRACE_JS = """<script>(function () {
  var svg = document.getElementById("UID"), plan = PLAN, timers = [];
  if (!svg) return;
  var msg = svg.querySelector("[data-msg]");
  function each(sel, f) { Array.prototype.forEach.call(svg.querySelectorAll(sel), f); }
  function node(id, on) { var g = document.getElementById(id); if (g) g.style.opacity = on ? 1 : 0.15; }
  function edge(id, on) {
    var e = document.getElementById(id); if (!e) return;
    e.style.strokeOpacity = on ? 1 : 0.12; e.style.stroke = on ? "#5b3cc4" : ""; e.style.strokeWidth = on ? 2 : "";
  }
  each("[data-walk]", function (b) { b.addEventListener("click", function () {
    var p = plan[b.getAttribute("data-walk")];
    timers.forEach(clearTimeout); timers = [];
    each("g[id^=UIDn]", function (g) { node(g.id, false); });
    each("line[id^=UIDe]", function (e) { edge(e.id, false); });
    msg.textContent = "";
    Object.keys(p.nodes).forEach(function (id) { var h = p.nodes[id];
      timers.push(setTimeout(function () { node(id, true); }, h * STEP_MS + 50)); });
    Object.keys(p.edges).forEach(function (id) {
      timers.push(setTimeout(function () { edge(id, true); }, p.edges[id] * STEP_MS)); });
    p.msgs.forEach(function (m, i) {
      timers.push(setTimeout(function () { msg.textContent = m; }, (i + 1) * STEP_MS)); });
  }); });
})();</script>"""


def walk_levels(nodes, edges, source, labels):
    """BFS from the source over the drawn graph, inbound, following only `labels`: {node: hop},
    and the edges the walk crossed, {(a, b): hop of a}."""
    into = {}
    for a, b, l in edges:
        if l in labels:
            into.setdefault(b, []).append((a, l))
    level, crossed, q = {source: 0}, {}, deque([source])
    while q:
        v = q.popleft()
        for u, _ in into.get(v, []):
            if u not in level:
                level[u] = level[v] + 1
                q.append(u)
            if level[u] == level[v] + 1:
                crossed[(u, v)] = level[u]
    return level, crossed


def svg(nodes, edges, source, after_fix=(), hub_edges=(), callouts=(), legend=(), title="", totals=None):
    """The drawing. after_fix: decision ids to ring; hub: node ids of the busiest record's chain
    (a light band along their edges); callouts: [(node id, number, text)]; legend: html lines."""
    keys, xs, key = layout(nodes, edges, source)
    drawn = [n for n in nodes if "x" in nodes[n]]
    minx, maxx = min(nodes[n]["x"] for n in drawn), max(nodes[n]["x"] for n in drawn)
    miny, maxy = min(nodes[n]["y"] for n in drawn), max(nodes[n]["y"] for n in drawn)
    pad_l, pad_r, pad_t, pad_b = 250, 280, 90, 70
    W, H = maxx - minx + pad_l + pad_r, maxy - miny + pad_t + pad_b
    X = lambda n: nodes[n]["x"] - minx + pad_l
    Y = lambda n: nodes[n]["y"] - miny + pad_t
    uid = "lv" + uuid.uuid4().hex[:8]
    out = [f'<svg id="{uid}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}" style="font-family:Helvetica,Arial,sans-serif;background:#fff">',
           '<defs><marker id="ah" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" '
           'orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="#b9b8b0"/></marker></defs>']
    # the hop ruler
    hops = {}
    for k in keys:
        if k % 2 == 0 and k > 0:
            hops[k // 2] = xs[k] - minx + pad_l
    for h, hx in hops.items():
        out.append(f'<text x="{hx:.0f}" y="{pad_t - 34}" font-size="11" fill="#6d5bd0" text-anchor="middle">hop {h}</text>')
    hubset = set(hub_edges)
    eids = {}
    for a, b, lab in edges:
        if "x" in nodes.get(a, {}) and "x" in nodes.get(b, {}):
            if (a, b) in hubset:
                out.append(f'<line x1="{X(a):.1f}" y1="{Y(a):.1f}" x2="{X(b):.1f}" y2="{Y(b):.1f}" '
                           'stroke="#cfc6f2" stroke-width="7" stroke-linecap="round"/>')
    for a, b, lab in edges:
        if "x" in nodes.get(a, {}) and "x" in nodes.get(b, {}):
            dx, dy = X(b) - X(a), Y(b) - Y(a)
            d = max((dx * dx + dy * dy) ** 0.5, 1)
            ex, ey = X(b) - dx / d * (R + 2), Y(b) - dy / d * (R + 2)
            eid = f"{uid}e{len(eids)}"
            eids[(a, b)] = eid
            out.append(f'<line id="{eid}" style="transition:stroke-opacity .3s,stroke .3s" x1="{X(a):.1f}" y1="{Y(a):.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="#c9c8c0" '
                       f'stroke-width="1" marker-end="url(#ah)"><title>{html.escape(lab)}</title></line>')
    ring = set(after_fix)
    nids = {n: f"{uid}n{i}" for i, n in enumerate(drawn)}
    for n in drawn:
        p = nodes[n]
        color = COLORS.get(p.get("outcome") if p["kind"] == "decision" else p["kind"], "#ddd")
        r = R + 3 if n == source else R
        tip = html.escape(p.get("tip", n))
        out.append(f'<g id="{nids[n]}" style="transition:opacity .3s"><title>{tip}</title><circle cx="{X(n):.1f}" cy="{Y(n):.1f}" r="{r}" fill="{color}" '
                   f'stroke="#fff" stroke-width="1.5"/>')
        if n in ring:
            out.append(f'<circle cx="{X(n):.1f}" cy="{Y(n):.1f}" r="{R + 3.5}" fill="none" stroke="{RING}" stroke-width="2.5"/>')
        out.append("</g>")
    for n, num, text, dy in callouts:
        if n not in nodes or "x" not in nodes[n]:
            continue
        left = n == source
        lines = text.split("\n")
        bx = X(n) - 26 if left else X(n) + 26
        by = Y(n) + dy
        w = max(len(l) for l in lines) * 6.1 + 30
        h = 13 * len(lines) + 10
        rx = bx - w if left else bx
        out.append(f'<line x1="{X(n):.1f}" y1="{Y(n):.1f}" x2="{(rx + w if left else rx):.1f}" y2="{by + h / 2:.1f}" '
                   f'stroke="#9d90e0" stroke-width="1"/>')
        out.append(f'<rect x="{rx:.1f}" y="{by:.1f}" width="{w:.0f}" height="{h:.0f}" rx="5" fill="#fff" '
                   f'stroke="#b9aef0" stroke-dasharray="4 3"/>')
        out.append(f'<circle cx="{rx + 12:.1f}" cy="{by + 11:.1f}" r="7" fill="{RING}"/>'
                   f'<text x="{rx + 12:.1f}" y="{by + 14.5:.1f}" font-size="10" fill="#fff" text-anchor="middle">{num}</text>')
        for i, line in enumerate(lines):
            out.append(f'<text x="{rx + 24:.1f}" y="{by + 15 + i * 13:.1f}" font-size="11" fill="#2a2a2a">'
                       f'{html.escape(line)}</text>')
    # The trace: a button starts its walk. Every node and edge dims, then each hop lights in turn,
    # with a running count; the full walk's answer comes last. A small script drives it, scoped to
    # this drawing's ids, so a notebook can show the view more than once.
    bx, plan = 20, {}
    for key, (label, labels) in WALKS.items():
        level, crossed = walk_levels(nodes, edges, source, set(labels))
        w = len(label) * 6.6 + 22
        fill, color = ("#5b3cc4", "#fff") if key == "both" else ("#fff", "#5b3cc4")
        out.append(f'<g data-walk="{key}" style="cursor:pointer"><rect x="{bx}" y="12" width="{w:.0f}" height="22" rx="11" '
                   f'fill="{fill}" stroke="#5b3cc4"/><text x="{bx + w / 2:.0f}" y="27" font-size="12" '
                   f'fill="{color}" text-anchor="middle" font-weight="600">{html.escape(label)}</text></g>')
        bx += w + 8
        if key == "both":
            out.append(f'<text x="{bx:.0f}" y="27" font-size="12" fill="#52514e">or only</text>')
            bx += 50
        hops = max(level.values())
        name = label if key != "both" else "both routes"
        msgs, reached = [], 0
        for h in range(1, hops + 1):
            reached += sum(1 for n, l in level.items() if l == h and nodes[n]["kind"] == "decision")
            msgs.append(f"{name}: hop {h}, {reached} drawn decisions reached")
        if totals and key in totals:
            t = totals[key]
            msgs.append(f"{label if key != 'both' else 'over both routes'}: {t['decisions']:,} decisions "
                        f"in the full walk, {t['after_fix']:,} after the fix")
        plan[key] = {"nodes": {nids[n]: level[n] for n in drawn if n in level},
                     "edges": {eid: crossed[ab] for ab, eid in eids.items() if ab in crossed},
                     "msgs": msgs}
    out.append(f'<text data-msg="1" x="{W - 20:.0f}" y="27" font-size="12" fill="#5b3cc4" text-anchor="end"></text>')
    out.append("</svg>")
    out.append(TRACE_JS.replace("UID", uid).replace("PLAN", json.dumps(plan)).replace("STEP_MS", str(int(STEP * 1000))))
    leg = "".join(f"<div>{l}</div>" for l in legend)
    return (f'<div style="font-family:Helvetica,Arial,sans-serif;font-size:12px;color:#1a1a1a">'
            f'<div style="color:#6d5bd0;font-size:11px;margin:2px 0">{html.escape(title)}</div>'
            f'<div style="overflow-x:auto">{"".join(out)}</div>'
            f'<div style="display:inline-block;border:1px dashed #b9aef0;border-radius:5px;padding:6px 10px;'
            f'margin-top:4px;line-height:1.6">{leg}</div></div>')


def chip(color, text, ring=False):
    style = (f"border:2.5px solid {RING};background:transparent" if ring else f"background:{color}")
    return (f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;{style};'
            f'margin:0 4px 0 10px;vertical-align:-1px"></span>{html.escape(text)}')
