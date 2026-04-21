"""Generate advisor progress-check slide deck as .pptx."""

import os
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
from pptx.oxml.ns import qn
from pptx.oxml import parse_xml
import copy

# ── Dimensions (16:9 widescreen) ─────────────────────────────────────────────
W, H = Inches(13.33), Inches(7.5)

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY    = RGBColor(0x1a, 0x2e, 0x4a)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
ACCENT  = RGBColor(0x2E, 0x86, 0xC1)   # blue
GREEN   = RGBColor(0x1E, 0x8B, 0x4C)
RED     = RGBColor(0xC0, 0x39, 0x2B)
YELLOW  = RGBColor(0xF3, 0x9C, 0x12)
LGRAY   = RGBColor(0xF2, 0xF2, 0xF2)
DGRAY   = RGBColor(0x44, 0x44, 0x44)
MGRAY   = RGBColor(0x88, 0x88, 0x88)

RESULTS = os.path.join(os.path.dirname(__file__), "results")
FIG = {
    "fig1": os.path.join(RESULTS, "fig1", "fig1_headline.png"),
    "fig2": os.path.join(RESULTS, "fig2", "fig2_overhead_comparison.png"),
    "fig3": os.path.join(RESULTS, "fig3", "fig3_scalability.png"),
    "fig4": os.path.join(RESULTS, "fig4", "fig4_burst_resilience.png"),
    "fig5": os.path.join(RESULTS, "fig5", "fig5_adaptive_grouping.png"),
    "fig6": os.path.join(RESULTS, "fig6", "fig6_ber_bitlength.png"),
    "sdc":  os.path.join(RESULTS, "fig_sdc", "fig_sdc.png"),
}

prs = Presentation()
prs.slide_width  = W
prs.slide_height = H

BLANK = prs.slide_layouts[6]   # completely blank


# ── Helpers ───────────────────────────────────────────────────────────────────

def add_rect(slide, x, y, w, h, fill=None, line=None):
    shape = slide.shapes.add_shape(1, x, y, w, h)
    shape.line.fill.background()
    if fill:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
    else:
        shape.fill.background()
    if line:
        shape.line.color.rgb = line
        shape.line.width = Pt(1)
    else:
        shape.line.fill.background()
    return shape


def add_text(slide, text, x, y, w, h,
             size=18, bold=False, color=WHITE,
             align=PP_ALIGN.LEFT, wrap=True, italic=False):
    txb = slide.shapes.add_textbox(x, y, w, h)
    tf  = txb.text_frame
    tf.word_wrap = wrap
    p   = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size  = Pt(size)
    run.font.bold  = bold
    run.font.color.rgb = color
    run.font.italic = italic
    return txb


def slide_header(slide, title, subtitle=None):
    """Navy top bar with title (and optional subtitle line)."""
    add_rect(slide, 0, 0, W, Inches(1.1), fill=NAVY)
    add_text(slide, title,
             Inches(0.35), Inches(0.1), Inches(12.6), Inches(0.72),
             size=28, bold=True, color=WHITE, align=PP_ALIGN.LEFT)
    if subtitle:
        add_text(slide, subtitle,
                 Inches(0.35), Inches(0.78), Inches(12.6), Inches(0.36),
                 size=15, bold=False, color=RGBColor(0xAA, 0xCC, 0xEE),
                 align=PP_ALIGN.LEFT)
    # thin accent line below header
    add_rect(slide, 0, Inches(1.1), W, Inches(0.04), fill=ACCENT)


def body_y():
    return Inches(1.2)


def add_bullet_box(slide, items, x, y, w, h, size=17, color=DGRAY,
                   bullet="•", spacing=1.15):
    txb = slide.shapes.add_textbox(x, y, w, h)
    tf  = txb.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after  = Pt(4)
        p.space_before = Pt(2)
        run = p.add_run()
        run.text = f"{bullet}  {item}"
        run.font.size  = Pt(size)
        run.font.color.rgb = color
    return txb


def add_table(slide, headers, rows, x, y, w, h,
              header_fill=NAVY, header_color=WHITE,
              alt_fill=LGRAY, font_size=14):
    n_cols = len(headers)
    n_rows = len(rows) + 1
    tbl = slide.shapes.add_table(n_rows, n_cols, x, y, w, h).table
    col_w = w // n_cols
    for c in range(n_cols):
        tbl.columns[c].width = col_w

    def cell_style(cell, text, fill, fg, bold=False, align=PP_ALIGN.CENTER):
        cell.text = text
        cell.fill.solid()
        cell.fill.fore_color.rgb = fill
        p = cell.text_frame.paragraphs[0]
        p.alignment = align
        run = p.runs[0] if p.runs else p.add_run()
        run.font.size  = Pt(font_size)
        run.font.bold  = bold
        run.font.color.rgb = fg

    for c, h in enumerate(headers):
        cell_style(tbl.cell(0, c), h, header_fill, header_color, bold=True)

    for r, row in enumerate(rows):
        bg = alt_fill if r % 2 == 1 else WHITE
        for c, val in enumerate(row):
            align = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER
            cell_style(tbl.cell(r + 1, c), val, bg, DGRAY, align=align)

    return tbl


def embed_figure(slide, path, x, y, w, h):
    if os.path.exists(path):
        slide.shapes.add_picture(path, x, y, w, h)
    else:
        box = add_rect(slide, x, y, w, h, fill=LGRAY, line=MGRAY)
        add_text(slide, f"[figure not found:\n{os.path.basename(path)}]",
                 x, y + h//2 - Inches(0.3), w, Inches(0.6),
                 size=12, color=MGRAY, align=PP_ALIGN.CENTER)


def add_note(slide, text):
    notes = slide.notes_slide
    tf = notes.notes_text_frame
    tf.text = text


def label_tag(slide, text, x, y, color=ACCENT):
    """Small colored pill label."""
    add_rect(slide, x, y, Inches(1.8), Inches(0.32), fill=color)
    add_text(slide, text, x + Inches(0.1), y + Inches(0.03),
             Inches(1.6), Inches(0.28), size=12, bold=True,
             color=WHITE, align=PP_ALIGN.CENTER)


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 1 — Title
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=NAVY)
add_rect(sl, 0, Inches(2.6), W, Inches(2.6), fill=RGBColor(0x10, 0x1E, 0x35))

add_text(sl,
         "Approximate ECC via\nFeistel-Permuted CRC Hashing",
         Inches(1), Inches(1.5), Inches(11.3), Inches(1.8),
         size=40, bold=True, color=WHITE, align=PP_ALIGN.CENTER)

add_text(sl,
         "Empirical characterization of correction capability, overhead, and failure modes",
         Inches(1.5), Inches(3.1), Inches(10.3), Inches(0.6),
         size=20, color=RGBColor(0xAA, 0xCC, 0xEE), align=PP_ALIGN.CENTER)

add_rect(sl, Inches(5.5), Inches(3.9), Inches(2.33), Inches(0.04), fill=ACCENT)

add_text(sl, "Advisor Progress Check  ·  2026",
         Inches(1), Inches(4.1), Inches(11.3), Inches(0.4),
         size=16, color=MGRAY, align=PP_ALIGN.CENTER, italic=True)

add_note(sl, "Frame immediately: 'probabilistic correction traded for lower overhead and intrinsic burst immunity.'")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 2 — Scheme in 60 Seconds
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "The Scheme in 60 Seconds",
             "Feistel permutation  →  CRC hash groups  →  DAG-guided solver")

BOX_Y = Inches(1.55)
BOX_H = Inches(4.5)
BOX_W = Inches(3.6)
GAP   = Inches(0.45)

panels = [
    ("1. Feistel Permutation", NAVY,
     ["Maps each bit's linear index to a 2D grid position using a key-derived bijection",
      "Provides spatial scrambling — no two keys produce the same layout",
      "Key insight: distributes burst errors uniformly, making them look random to the solver"]),
    ("2. CRC Hash Groups", ACCENT,
     ["Each row and each column of the grid carries a CRC checksum",
      "CRC-8 / CRC-16 / CRC-32 control the overhead budget (25% / 50% / 100%)",
      "Mismatched hashes localise the corrupted region for the solver"]),
    ("3. DAG-Guided Solver", GREEN,
     ["Nodes ordered by fewest covered bits — smallest search space first",
      "Exhaustively tests flip combinations until hash agreement is restored",
      "Returns exact corrected bitstring, or flags failure if none found"]),
]

for i, (title, color, bullets) in enumerate(panels):
    x = Inches(0.3) + i * (BOX_W + GAP)
    add_rect(sl, x, BOX_Y, BOX_W, BOX_H, fill=LGRAY, line=RGBColor(0xCC,0xCC,0xCC))
    add_rect(sl, x, BOX_Y, BOX_W, Inches(0.48), fill=color)
    add_text(sl, title, x + Inches(0.15), BOX_Y + Inches(0.07),
             BOX_W - Inches(0.2), Inches(0.38),
             size=15, bold=True, color=WHITE)
    add_bullet_box(sl, bullets,
                   x + Inches(0.18), BOX_Y + Inches(0.6),
                   BOX_W - Inches(0.25), Inches(3.6),
                   size=14, color=DGRAY, bullet="▸")

    if i < 2:
        add_text(sl, "→", x + BOX_W + Inches(0.1),
                 BOX_Y + Inches(2.0), GAP, Inches(0.5),
                 size=28, bold=True, color=ACCENT, align=PP_ALIGN.CENTER)

add_note(sl, "Keep this to one slide — no implementation detail needed. Emphasise the permutation's double duty: scrambling AND burst equalization.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 3 — Headline Correction Capability (Fig 1)
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "What It Corrects  —  4096-bit block, 30 keys",
             "Success rate, solve time, and hash comparisons vs injected bit-flips")

embed_figure(sl, FIG["fig1"], Inches(0.2), Inches(1.2), Inches(8.8), Inches(5.8))

BY = body_y()
callouts = [
    (GREEN,  "CRC-32 (100% OH)", "100% success through\n266 flips (~6.5% BER)"),
    (ACCENT, "CRC-16 (50% OH)",  "100% through 100 flips;\ngraceful degradation to 190"),
    (RED,    "CRC-8 (25% OH)",   "Sharp cliff at 40 flips —\nnot gradual"),
]
for i, (color, label, desc) in enumerate(callouts):
    cy = BY + Inches(0.1) + i * Inches(1.8)
    add_rect(sl, Inches(9.2), cy, Inches(0.08), Inches(1.4), fill=color)
    add_text(sl, label,  Inches(9.4), cy,               Inches(3.7), Inches(0.4),
             size=14, bold=True, color=color)
    add_text(sl, desc,   Inches(9.4), cy + Inches(0.38), Inches(3.7), Inches(0.9),
             size=13, color=DGRAY)

add_note(sl, "Lead with CRC-32 strength. Show the CRC-8 cliff openly — do not hide it. The cliff shape (sharp, not gradual) matters.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 4 — Honest Overhead vs BCH (Fig 2)
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Honest Overhead Comparison vs BCH  —  4096-bit block",
             "Theoretical BCH vs actual BCH needed for 95% success vs our operating points")

embed_figure(sl, FIG["fig2"], Inches(0.2), Inches(1.2), Inches(8.8), Inches(5.8))

points = [
    ("Honest BCH gap",
     "BCH t=10 needs 63% overhead for 95% success — vs 35% theoretical.\n1.8× gap from Poisson variance in per-block error count.", YELLOW),
    ("Our operating points",
     "CRC-16 (50% OH): 100 flips at 95%.\nCRC-32 (100% OH): 200+ flips.\nComparable to honest BCH at lower or equal overhead.", ACCENT),
    ("Decode complexity",
     "CRC hash checks are 10–30× cheaper than BCH GF field operations\nat all tested correction targets.", GREEN),
]
for i, (label, desc, color) in enumerate(points):
    cy = body_y() + Inches(0.05) + i * Inches(1.78)
    add_rect(sl, Inches(9.15), cy, Inches(3.98), Inches(1.6),
             fill=LGRAY, line=RGBColor(0xCC, 0xCC, 0xCC))
    add_rect(sl, Inches(9.15), cy, Inches(0.12), Inches(1.6), fill=color)
    add_text(sl, label, Inches(9.35), cy + Inches(0.08),
             Inches(3.6), Inches(0.35), size=13, bold=True, color=DGRAY)
    add_text(sl, desc,  Inches(9.35), cy + Inches(0.42),
             Inches(3.65), Inches(1.1), size=12, color=DGRAY)

add_note(sl, "Flag proactively: BCH anomaly at 128 bits in Fig 3 is a tiling-boundary artifact. Explain honest overhead methodology if asked: you measured BCH success at each flip count, found the 95% threshold, divided parity bits by block size.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 5 — Burst Immunity (Fig 4)
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Burst Immunity is Intrinsic  —  4096-bit, 16-bit CRC, 30 keys",
             "Feistel shuffle distributes burst errors uniformly — curves overlap almost perfectly")

embed_figure(sl, FIG["fig4"], Inches(0.5), Inches(1.2), Inches(9.0), Inches(5.8))

add_rect(sl, Inches(9.7), Inches(1.3), Inches(3.4), Inches(5.5),
         fill=RGBColor(0xE8, 0xF4, 0xE8), line=GREEN)
add_rect(sl, Inches(9.7), Inches(1.3), Inches(3.4), Inches(0.45), fill=GREEN)
add_text(sl, "Key result", Inches(9.8), Inches(1.32), Inches(3.1), Inches(0.38),
         size=14, bold=True, color=WHITE)

key_points = [
    "Random and burst success curves overlap across the full flip range",
    "Solver search effort (combo evaluations) is nearly identical for both modes",
    "The Feistel permutation converts burst errors into random spatial distribution — the solver never sees the difference",
    "BCH requires explicit interleaving to match this; our scheme provides it architecturally with no extra mechanism",
]
add_bullet_box(sl, key_points, Inches(9.8), Inches(1.85),
               Inches(3.2), Inches(4.7), size=13, color=DGRAY, bullet="✓")

add_note(sl, "This is the cleanest result. Let it breathe. If asked: 'how tight is the overlap?' — answer: indistinguishable within key-sample variance at every flip count tested.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 6 — Flips/Node Unified Model
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Unified Model: The Flips-per-Node Threshold",
             "A single variable — flips ÷ √L — predicts solver success across all block sizes and configurations")

# Explanation text left side
add_text(sl,
         "Success rate collapses on one curve when we measure\nflips per row-node (= flips ÷ √L) instead of raw flip count or BER.",
         Inches(0.4), Inches(1.3), Inches(5.8), Inches(0.9),
         size=16, color=DGRAY)

# Threshold table
add_table(sl,
    ["Flips / row-node", "Observed success rate", "Regime"],
    [
        ["< 1.6",  "~100%",  "Safe"],
        ["~2.2",   "~70%",   "Degrading"],
        ["> 3.2",  "~0%",    "Failed"],
    ],
    Inches(0.4), Inches(2.35), Inches(5.9), Inches(2.0),
    font_size=16,
)

# Evidence table
add_text(sl, "Evidence — same curve across experiments:",
         Inches(0.4), Inches(4.55), Inches(5.9), Inches(0.4),
         size=14, bold=True, color=DGRAY)
add_table(sl,
    ["Source", "L", "Flips", "Flips/node", "Success"],
    [
        ["Fig 3", "1024", "51",  "1.59", "100%"],
        ["Fig 2", "4096", "100", "1.56", "100%"],
        ["Fig 3", "2048", "102", "2.22", "70%"],
        ["Fig 2", "4096", "125", "1.95", "70%"],
        ["Fig 3", "4096", "204", "3.19", "0%"],
        ["Fig 2", "4096", "200", "3.12", "~5%"],
    ],
    Inches(0.4), Inches(5.05), Inches(5.9), Inches(2.0),
    font_size=13,
)

# Right side: insight callout
add_rect(sl, Inches(6.8), Inches(1.3), Inches(6.2), Inches(5.8),
         fill=RGBColor(0xEA, 0xF2, 0xFB), line=ACCENT)
add_rect(sl, Inches(6.8), Inches(1.3), Inches(6.2), Inches(0.5), fill=ACCENT)
add_text(sl, "Why flips/node is the right variable",
         Inches(6.95), Inches(1.33), Inches(5.9), Inches(0.4),
         size=15, bold=True, color=WHITE)

insight_bullets = [
    "√L = number of row-groups in the grid",
    "Flips ÷ √L = average solver load per DAG node",
    "The solver's difficulty is per-node, not total",
    "This collapses Fig 1, Fig 2, Fig 3, and Fig 6\nonto a single predictive axis",
    "Empirically derived — validation on unseen\nblock sizes is the proposed next experiment",
]
add_bullet_box(sl, insight_bullets,
               Inches(6.95), Inches(1.95), Inches(5.9), Inches(5.0),
               size=14, color=DGRAY, bullet="→")

add_note(sl, "This is the main theoretical contribution. Spend extra time. If asked 'is this derived or fit?' — answer: the functional form comes from the architecture (√L is the node count); the threshold values are empirical. Validation experiment will test this on L=768 and L=3072.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 7 — SDC Characterization
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Safety: Silent Data Corruption (SDC)  —  50 keys/cell",
             "When the solver returns a wrong answer that satisfies all hash checks")

# SDC table
add_table(sl,
    ["Configuration", "SDC rate", "Status"],
    [
        ["CRC-8,  group-size=1",  "78.6%", "⚠ Unsafe"],
        ["CRC-16, group-size=1",  "14.2%", "⚠ Risky"],
        ["CRC-16, group-size=2",  "~0%",   "✓ Safe"],
        ["CRC-32, group-size=1",  "0%",    "✓ Safe"],
    ],
    Inches(0.4), Inches(1.3), Inches(5.5), Inches(2.4),
    font_size=16,
)

add_text(sl, "CRC-32: zero silent errors observed across all tested configurations.\nAll failures are detected — never silent.",
         Inches(0.4), Inches(3.85), Inches(5.5), Inches(0.8),
         size=15, bold=True, color=GREEN)

embed_figure(sl, FIG["sdc"], Inches(6.1), Inches(1.2), Inches(6.9), Inches(5.8))

add_text(sl,
         "CRC width selection is not just a\nperformance knob — it is a safety boundary.",
         Inches(0.4), Inches(4.8), Inches(5.5), Inches(0.9),
         size=15, italic=True, color=DGRAY)

add_note(sl, "Do not soften the CRC-8 number. Present it as alarming. You found it, you characterised it — that is intellectual credit. 'This is why CRC width selection is a safety boundary, not just a performance knob.'")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 8 — Honest Tradeoffs vs BCH
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Honest Positioning vs BCH",
             "Different points in the design space — not a universal replacement")

add_table(sl,
    ["Property", "Our scheme (CRC-16, gs=2)", "BCH (t=10, 4096b)"],
    [
        ["Overhead (honest, 95% success)", "50%",                  "~63%"],
        ["Correction guarantee",           "Probabilistic",        "Deterministic ✓"],
        ["Burst immunity",                 "Intrinsic ✓",          "Needs interleaving"],
        ["SDC risk",                       "~0% (gs=2) ✓",         "0% ✓"],
        ["Decode cost",                    "O(L) hash checks ✓",   "O(L · GF ops)"],
        ["Overhead scaling",               "O(1/√L) — improves ✓", "Flat across sizes"],
        ["Theoretical guarantees",         "Empirical model",      "Algebraic bounds ✓"],
    ],
    Inches(0.4), Inches(1.3), Inches(12.5), Inches(4.3),
    font_size=15,
)

add_text(sl,
         "BCH wins on: deterministic correction, zero SDC at any width, established theory.\n"
         "We win on: overhead at scale, intrinsic burst immunity, decode cost, O(1/√L) scaling.",
         Inches(0.4), Inches(5.75), Inches(12.5), Inches(0.8),
         size=15, color=DGRAY)

add_note(sl, "Build this table collaboratively in narration. Do not claim every cell favours your scheme — the advisor will respect honest accounting far more. BCH determinism is a real advantage; say so.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 9 — Proposed Next Experiments
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Proposed Next Experiments",
             "Ordered by effort — all directly address current gaps in the argument")

exps = [
    (RED,    "Low effort",    "SDC rate vs flip count sweep",
     "Does SDC spike near the correction cliff? Does CRC-32 hold zero SDC even at 300+ flips?\nSweep flip=0–300 in steps of 25, 4096-bit, CRC-16 and CRC-32, 50 keys.\nCloses the 'is SDC constant or does it spike?' question the advisor will ask."),
    (YELLOW, "Low effort",    "Solver runtime tail distribution",
     "Full histogram of combo evaluations per trial (not just mean). Is the exponential tail thin?\nRe-analyse existing data + short additional run.\nNeeded before claiming 'rarely hits exponential case in practice.'"),
    (ACCENT, "Medium effort", "Flips/node model — out-of-sample validation",
     "Test unified threshold model on L=768 and L=3072 (not used to derive it).\nOne clean out-of-sample prediction is worth more than ten in-sample fits.\nTurns empirical observation into a validated predictive model."),
    (GREEN,  "High effort",   "LDPC comparison at matched overhead",
     "Compare against LDPC (the modern probabilistic ECC) at 50% and 100% overhead.\nAddresses 'why not just use LDPC?' — needed for publication-quality positioning.\nEstimate ~1 week to implement or integrate a reference library."),
]

for i, (color, effort, title, desc) in enumerate(exps):
    col = i % 2
    row = i // 2
    x = Inches(0.3)  + col * Inches(6.55)
    y = Inches(1.35) + row * Inches(2.85)
    add_rect(sl, x, y, Inches(6.25), Inches(2.6),
             fill=LGRAY, line=RGBColor(0xCC, 0xCC, 0xCC))
    add_rect(sl, x, y, Inches(6.25), Inches(0.45), fill=color)
    add_text(sl, title,  x + Inches(0.15), y + Inches(0.06),
             Inches(5.5), Inches(0.35), size=14, bold=True, color=WHITE)
    add_text(sl, f"[{effort}]", x + Inches(4.7), y + Inches(0.06),
             Inches(1.4), Inches(0.35), size=11, color=WHITE,
             italic=True, align=PP_ALIGN.RIGHT)
    add_text(sl, desc, x + Inches(0.18), y + Inches(0.56),
             Inches(5.9), Inches(1.9), size=12, color=DGRAY)

add_note(sl, "Frame as 'here is what I think comes next' not 'here is what I have not done'. The advisor may reprioritise — let them.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 10 — Open Questions
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Open Questions",
             "Theoretical gaps and deployment unknowns")

questions = [
    ("Theory",      ACCENT, "Can the flips/node threshold be derived analytically?",
     "The functional form comes from the architecture (√L = node count). The threshold values\nare empirical. Is there a derivation from CRC collision probability + DAG structure?"),
    ("Deployment",  NAVY,   "What is the per-key variance in success rate?",
     "Current results average over 20–50 keys. In deployment, a system uses one key.\nThe per-key success rate distribution is not characterised."),
    ("Adversarial", RED,    "Is there a structured error pattern that defeats the Feistel permutation?",
     "Fig 4 shows natural burst errors are neutralised. But a structured adversary (or\nphysical fault like row-hammer) could target specific grid positions."),
    ("Extension",   GREEN,  "Does the scheme extend naturally to erasures?",
     "Erasure channels (known-position errors) are common in flash and network coding.\nThe DAG solver may simplify significantly when positions are known."),
]

for i, (tag, color, q, detail) in enumerate(questions):
    col = i % 2
    row = i // 2
    x = Inches(0.3)  + col * Inches(6.55)
    y = Inches(1.35) + row * Inches(2.7)
    add_rect(sl, x, y, Inches(6.25), Inches(2.45),
             fill=LGRAY, line=RGBColor(0xCC, 0xCC, 0xCC))
    label_tag(sl, tag, x + Inches(0.15), y + Inches(0.12), color=color)
    add_text(sl, q, x + Inches(0.15), y + Inches(0.55),
             Inches(5.9), Inches(0.55), size=14, bold=True, color=DGRAY)
    add_text(sl, detail, x + Inches(0.15), y + Inches(1.12),
             Inches(5.9), Inches(1.2), size=12, color=DGRAY)

add_note(sl, "This slide signals you are thinking about theory, not just running experiments. The advisor will have opinions on which of these is tractable — let them talk.")


# ═══════════════════════════════════════════════════════════════════════════════
# BACKUP SLIDES
# ═══════════════════════════════════════════════════════════════════════════════

def backup_slide(title, fig_key, subtitle=""):
    s = prs.slides.add_slide(BLANK)
    add_rect(s, 0, 0, W, H, fill=WHITE)
    slide_header(s, f"[Backup] {title}", subtitle)
    add_rect(s, Inches(0.4), Inches(1.18), Inches(0.9), Inches(0.3),
             fill=RGBColor(0x99, 0x99, 0x99))
    add_text(s, "BACKUP", Inches(0.42), Inches(1.19), Inches(0.88), Inches(0.26),
             size=11, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    embed_figure(s, FIG[fig_key], Inches(0.8), Inches(1.55), Inches(11.7), Inches(5.7))
    return s

backup_slide("Scalability: Overhead vs Block Size",
             "fig3", "16-bit CRC, group-size=1  ·  Our O(1/√L) scaling vs flat BCH overhead")
backup_slide("BER × Block Size Surface",
             "fig6", "16-bit CRC, 20 keys/cell  ·  Success rate as function of BER and block size")
backup_slide("Adaptive Grouping: Hash Width Sweep",
             "fig5", "Overhead and correction tradeoffs across grouping strategies and CRC widths")


# ── Save ──────────────────────────────────────────────────────────────────────
OUT = os.path.join(os.path.dirname(__file__), "advisor_slides.pptx")
prs.save(OUT)
print(f"Saved: {OUT}")
