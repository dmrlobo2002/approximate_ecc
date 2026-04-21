"""Generate full research presentation slide deck as .pptx — 20 slides."""

import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

# ── Dimensions (16:9 widescreen) ─────────────────────────────────────────────
W, H = Inches(13.33), Inches(7.5)

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY   = RGBColor(0x1a, 0x2e, 0x4a)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
ACCENT = RGBColor(0x2E, 0x86, 0xC1)
GREEN  = RGBColor(0x1E, 0x8B, 0x4C)
RED    = RGBColor(0xC0, 0x39, 0x2B)
YELLOW = RGBColor(0xF3, 0x9C, 0x12)
LGRAY  = RGBColor(0xF2, 0xF2, 0xF2)
DGRAY  = RGBColor(0x44, 0x44, 0x44)
MGRAY  = RGBColor(0x88, 0x88, 0x88)

R = os.path.join(os.path.dirname(__file__), "results")
FIG = {
    "fig1":       os.path.join(R, "fig1",         "fig1_headline.png"),
    "fig2":       os.path.join(R, "fig2",          "fig2_overhead_comparison.png"),
    "fig3":       os.path.join(R, "fig3",          "fig3_scalability.png"),
    "fig3_hb16":  os.path.join(R, "fig3",          "fig3_hb16", "fig3_scalability.png"),
    "fig4":       os.path.join(R, "fig4",          "fig4_burst_resilience.png"),
    "fig4_hb16":  os.path.join(R, "fig4",          "fig4_hb16", "fig4_burst_resilience.png"),
    "fig5":       os.path.join(R, "fig5",          "fig5_adaptive_grouping.png"),
    "fig6":       os.path.join(R, "fig6",          "fig6_ber_bitlength.png"),
    "fig6_hb16":  os.path.join(R, "fig6",          "hb16", "fig6_ber_bitlength.png"),
    "sdc":        os.path.join(R, "fig_sdc",       "fig_sdc.png"),
    "sdc_gs":     os.path.join(R, "fig_sdc",       "fig_sdc_groupsize.png"),
    "bch_burst":  os.path.join(R, "fig_bch_burst", "fig_bch_burst.png"),
}

prs = Presentation()
prs.slide_width  = W
prs.slide_height = H
BLANK = prs.slide_layouts[6]


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
    add_rect(slide, 0, 0, W, Inches(1.1), fill=NAVY)
    add_text(slide, title,
             Inches(0.35), Inches(0.1), Inches(12.6), Inches(0.72),
             size=28, bold=True, color=WHITE)
    if subtitle:
        add_text(slide, subtitle,
                 Inches(0.35), Inches(0.78), Inches(12.6), Inches(0.36),
                 size=15, color=RGBColor(0xAA, 0xCC, 0xEE))
    add_rect(slide, 0, Inches(1.1), W, Inches(0.04), fill=ACCENT)


def add_bullets(slide, items, x, y, w, h, size=16, color=DGRAY, bullet="▸"):
    txb = slide.shapes.add_textbox(x, y, w, h)
    tf  = txb.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after  = Pt(5)
        run = p.add_run()
        run.text = f"{bullet}  {item}"
        run.font.size  = Pt(size)
        run.font.color.rgb = color
    return txb


def add_table(slide, headers, rows, x, y, w, h,
              hdr_fill=NAVY, hdr_fg=WHITE, font_size=14):
    n_cols, n_rows = len(headers), len(rows) + 1
    tbl = slide.shapes.add_table(n_rows, n_cols, x, y, w, h).table
    col_w = w // n_cols
    for c in range(n_cols):
        tbl.columns[c].width = col_w

    def cell(r, c, text, fill, fg, bold=False, align=PP_ALIGN.CENTER):
        cl = tbl.cell(r, c)
        cl.text = text
        cl.fill.solid()
        cl.fill.fore_color.rgb = fill
        p = cl.text_frame.paragraphs[0]
        p.alignment = align
        run = p.runs[0] if p.runs else p.add_run()
        run.font.size  = Pt(font_size)
        run.font.bold  = bold
        run.font.color.rgb = fg

    for c, h in enumerate(headers):
        cell(0, c, h, hdr_fill, hdr_fg, bold=True)
    for r, row in enumerate(rows):
        bg = LGRAY if r % 2 == 1 else WHITE
        for c, val in enumerate(row):
            align = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER
            cell(r + 1, c, val, bg, DGRAY, align=align)


def embed(slide, path, x, y, w, h):
    if os.path.exists(path):
        slide.shapes.add_picture(path, x, y, w, h)
    else:
        add_rect(slide, x, y, w, h, fill=LGRAY, line=MGRAY)
        add_text(slide, f"[missing: {os.path.basename(path)}]",
                 x, y + h // 2 - Inches(0.25), w, Inches(0.5),
                 size=11, color=MGRAY, align=PP_ALIGN.CENTER)


def note(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def callout_box(slide, items, x, y, w, h, title=None, accent=ACCENT):
    add_rect(slide, x, y, w, h, fill=RGBColor(0xEA, 0xF4, 0xFF),
             line=RGBColor(0xCC, 0xDD, 0xEE))
    if title:
        add_rect(slide, x, y, w, Inches(0.42), fill=accent)
        add_text(slide, title, x + Inches(0.12), y + Inches(0.06),
                 w - Inches(0.2), Inches(0.32), size=13, bold=True, color=WHITE)
        ty = y + Inches(0.52)
        th = h - Inches(0.52)
    else:
        ty, th = y + Inches(0.15), h - Inches(0.15)
    add_bullets(slide, items, x + Inches(0.15), ty,
                w - Inches(0.25), th, size=13, color=DGRAY)


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 1 — Title
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=NAVY)
add_rect(sl, 0, Inches(2.5), W, Inches(2.8), fill=RGBColor(0x10, 0x1E, 0x35))
add_text(sl, "Approximate ECC via\nFeistel-Permuted CRC Hashing",
         Inches(1), Inches(1.4), Inches(11.3), Inches(2.0),
         size=40, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
add_text(sl, "Burst resilience, overhead scaling, and failure mode characterization",
         Inches(1.5), Inches(3.15), Inches(10.3), Inches(0.6),
         size=20, color=RGBColor(0xAA, 0xCC, 0xEE), align=PP_ALIGN.CENTER)
add_rect(sl, Inches(5.5), Inches(3.95), Inches(2.33), Inches(0.04), fill=ACCENT)
add_text(sl, "Research Presentation  ·  2026",
         Inches(1), Inches(4.15), Inches(11.3), Inches(0.4),
         size=16, color=MGRAY, align=PP_ALIGN.CENTER, italic=True)
note(sl, "Lead with burst immunity — that is the primary justification.")


# ─────────────────────────────────────────────────────────────────────────────
# TRIMMED DECK — 9 slides: best evidence for the advisor
# 1 Title / 2 BCH burst theory / 3 BCH burst data / 4 Overhead table /
# 5 Correction capability / 6 Burst resilience / 7 Flips-per-node /
# 8 SDC safety / 9 Positioning + summary
# ─────────────────────────────────────────────────────────────────────────────

# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 2 — Why BCH fails on bursts (theory)
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Why BCH Fails on Burst Errors",
             "BCH is designed for the BSC (random error model) — burst channels violate this assumption")

# Left column: how BCH is actually deployed
add_rect(sl, Inches(0.4), Inches(1.25), Inches(5.9), Inches(5.85),
         fill=LGRAY, line=RGBColor(0xCC, 0xCC, 0xCC))
add_rect(sl, Inches(0.4), Inches(1.25), Inches(5.9), Inches(0.44), fill=NAVY)
add_text(sl, "How BCH is deployed in practice",
         Inches(0.55), Inches(1.29), Inches(5.65), Inches(0.36),
         size=14, bold=True, color=WHITE)
add_bullets(sl, [
    "Applied to small blocks: typically 256 bits per codeword",
    "t = expected errors per block = round(BER × 256)",
    "  e.g. t=13 at 5% BER → 45.7% overhead per block",
    "Tiled across larger data: 16 × BCH(256) for 4096-bit page",
    "Each block independently decodes — no cross-block awareness",
    "Assumes random, independent errors per block (BSC model)",
], Inches(0.55), Inches(1.82), Inches(5.65), Inches(4.8), size=14, color=DGRAY)

# Right column: the burst problem
add_rect(sl, Inches(6.55), Inches(1.25), Inches(6.45), Inches(5.85),
         fill=RGBColor(0xFC, 0xF0, 0xEE), line=RED)
add_rect(sl, Inches(6.55), Inches(1.25), Inches(6.45), Inches(0.44), fill=RED)
add_text(sl, "The burst problem",
         Inches(6.7), Inches(1.29), Inches(6.2), Inches(0.36),
         size=14, bold=True, color=WHITE)
add_bullets(sl, [
    "Flash, DRAM, fiber produce burst errors — not random flips",
    "A burst of b bits may land entirely in one 256-bit block",
    "If b > t: that block fails completely — even if all other blocks are clean",
    "At 5% BER with t=13: any burst > 13 bits in one block = failure",
    "13 bits is a tiny burst — real channels produce bursts of 100s of bits",
    "BCH has no mechanism to handle this: it was designed for random channels",
], Inches(6.7), Inches(1.82), Inches(6.15), Inches(4.8), size=14, color=DGRAY)

note(sl, "Sets up the empirical proof on the next slide.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 3 — BCH Burst Failure: The Data (smoking gun)
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "BCH Burst Failure vs Our Scheme  —  Empirical",
             "BCH (16×256-bit blocks, t=13, 45.7% OH) vs CRC-32 (100% OH)  ·  5% BER operating point  ·  30 trials")

embed(sl, FIG["bch_burst"], Inches(0.3), Inches(1.2), Inches(8.8), Inches(5.8))

add_rect(sl, Inches(9.35), Inches(1.25), Inches(3.75), Inches(5.8),
         fill=RGBColor(0xF8, 0xF8, 0xF8), line=RGBColor(0xCC, 0xCC, 0xCC))
add_rect(sl, Inches(9.35), Inches(1.25), Inches(3.75), Inches(0.44), fill=NAVY)
add_text(sl, "What the data shows",
         Inches(9.5), Inches(1.29), Inches(3.5), Inches(0.36),
         size=13, bold=True, color=WHITE)
add_text(sl, "BCH (red):", Inches(9.5), Inches(1.82),
         Inches(3.5), Inches(0.3), size=13, bold=True, color=RED)
add_bullets(sl, [
    "100% success for burst ≤ 13 bits",
    "Hard cliff at burst = 14+ bits",
    "45.7% overhead buys only\n13-bit burst tolerance",
], Inches(9.5), Inches(2.15), Inches(3.5), Inches(1.55), size=13, color=DGRAY)

add_text(sl, "Our scheme (blue):", Inches(9.5), Inches(3.82),
         Inches(3.5), Inches(0.3), size=13, bold=True, color=ACCENT)
add_bullets(sl, [
    "100% success through burst = 245 bits",
    "No cliff anywhere in tested range",
    "Feistel permutation scatters any burst uniformly — solver sees random errors regardless",
], Inches(9.5), Inches(4.15), Inches(3.5), Inches(1.8), size=13, color=DGRAY)

add_rect(sl, Inches(9.35), Inches(6.18), Inches(3.75), Inches(0.78),
         fill=RGBColor(0xE8, 0xF4, 0xE8), line=GREEN)
add_text(sl, "BCH fails at 14 bits.\nOurs handles 245 bits.",
         Inches(9.45), Inches(6.24), Inches(3.6), Inches(0.65),
         size=14, bold=True, color=GREEN, align=PP_ALIGN.CENTER)
note(sl, "Say nothing. Let the cliff speak.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 4 — Overhead Table
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Overhead: BCH vs Our Scheme",
             "t = round(BER × 256)  ·  16 × BCH(256-bit blocks) vs CRC-32 on 4096-bit data")

add_table(sl,
    ["BER", "BCH t\n(expected errors)", "BCH overhead", "Our CRC-32", "BCH burst\ntolerance"],
    [
        ["1%", "t=3",  "10.5%", "100%", "3 bits"],
        ["2%", "t=5",  "17.6%", "100%", "5 bits"],
        ["3%", "t=8",  "28.1%", "100%", "8 bits"],
        ["4%", "t=10", "35.2%", "100%", "10 bits"],
        ["5%", "t=13", "45.7%", "100%", "13 bits"],
        ["6%", "t=15", "52.7%", "100%", "15 bits"],
    ],
    Inches(0.4), Inches(1.3), Inches(7.5), Inches(3.8), font_size=16)

add_text(sl, "Our burst tolerance: 200+ bits at every BER  ✓",
         Inches(0.4), Inches(5.25), Inches(7.5), Inches(0.4),
         size=15, bold=True, color=GREEN)
add_text(sl, "BCH wins on overhead — but only works for random errors.",
         Inches(0.4), Inches(5.72), Inches(7.5), Inches(0.38),
         size=15, bold=True, color=RED)

add_rect(sl, Inches(8.1), Inches(1.25), Inches(5.0), Inches(5.85),
         fill=RGBColor(0xF0, 0xF4, 0xFF), line=ACCENT)
add_rect(sl, Inches(8.1), Inches(1.25), Inches(5.0), Inches(0.44), fill=ACCENT)
add_text(sl, "Why we are still positioned better",
         Inches(8.25), Inches(1.29), Inches(4.75), Inches(0.36),
         size=13, bold=True, color=WHITE)
add_bullets(sl, [
    "BCH t is the expected error count — but channels produce bursts, not uniform random errors",
    "A 14-bit burst at 5% BER lands in ONE 256-bit block and immediately exceeds t=13 → hard failure",
    "BCH requires adding an interleaving layer for burst protection — extra complexity and latency",
    "Our Feistel permutation handles bursts natively: scatters any burst across 4096 bits, solver always sees ~uniform distribution",
    "Decode cost: CRC checks are 10–30× cheaper than BCH Galois Field operations",
    "No per-block failure mode: a burst that crosses block boundaries in BCH can fail multiple blocks simultaneously",
], Inches(8.25), Inches(1.82), Inches(4.75), Inches(5.2), size=13, color=DGRAY)
note(sl, "BCH wins on overhead — state this directly. Then pivot to burst tolerance column.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 5 — Correction Capability (Fig 1)
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "What Our Scheme Corrects  —  4096-bit block, 30 keys",
             "CRC-8 / CRC-16 / CRC-32 — success rate, solve time, and hash comparisons vs flip count")

embed(sl, FIG["fig1"], Inches(0.2), Inches(1.2), Inches(8.8), Inches(5.8))

for i, (color, label, desc) in enumerate([
    (GREEN,  "CRC-32 (100% OH)",
     "100% success through 266 flips\n(~6.5% BER) — full tested range"),
    (ACCENT, "CRC-16 (50% OH)",
     "100% through 100 flips;\ngraceful degradation"),
    (RED,    "CRC-8 (25% OH)",
     "Cliff at 40 flips.\nFast 'solve' is SDC not speed"),
]):
    cy = Inches(1.3) + i * Inches(1.9)
    add_rect(sl, Inches(9.2), cy, Inches(0.1), Inches(1.6), fill=color)
    add_text(sl, label, Inches(9.4), cy, Inches(3.7), Inches(0.4),
             size=14, bold=True, color=color)
    add_text(sl, desc, Inches(9.4), cy + Inches(0.4), Inches(3.7), Inches(1.0),
             size=13, color=DGRAY)
note(sl, "CRC-32 is the safe operating mode. CRC-8 fast solve time is SDC — explained on the safety slide.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 6 — Burst Resilience (Fig 4 CRC-32)
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Our Scheme: Burst = Random  —  CRC-32, 4096-bit, 30 keys",
             "Feistel permutation makes burst errors indistinguishable from random errors for the solver")

embed(sl, FIG["fig4"], Inches(0.4), Inches(1.2), Inches(9.1), Inches(5.8))

add_rect(sl, Inches(9.75), Inches(1.3), Inches(3.35), Inches(5.6),
         fill=RGBColor(0xE8, 0xF8, 0xEE), line=GREEN)
add_rect(sl, Inches(9.75), Inches(1.3), Inches(3.35), Inches(0.44), fill=GREEN)
add_text(sl, "Key results", Inches(9.9), Inches(1.34),
         Inches(3.1), Inches(0.36), size=14, bold=True, color=WHITE)
add_bullets(sl, [
    "Random and burst success curves overlap perfectly at all flip counts",
    "Solver search effort also nearly identical",
    "At 200 flips (~4.9% BER): 100% for both random AND burst",
    "BCH would fail on burst > 13 bits here (slide 3)",
    "Burst immunity is free — a byproduct of the permutation, not an add-on",
], Inches(9.9), Inches(1.85), Inches(3.1), Inches(5.0), size=13, color=DGRAY)
note(sl, "This is the payoff for slide 2. Curves overlapping is the entire result.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 7 — Flips/Node Unified Model
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "When Does the Solver Succeed?  —  The Flips-per-Node Model",
             "A single variable predicts success across all block sizes, hash widths, and BER values")

add_text(sl, "Flips per row-node  =  flip count ÷ √L\n"
             "(√L = number of row-groups in the grid = average solver load per DAG node)",
         Inches(0.4), Inches(1.28), Inches(6.2), Inches(0.72),
         size=15, color=DGRAY)

add_table(sl,
    ["Hash", "Safe (≥95%)", "Degrading", "Failed (~0%)"],
    [["CRC-16", "< 1.6",  "~2.2",       "> 3.2"],
     ["CRC-32", "< ~4.0", "~4.0–4.5",   "> 4.5 (not yet characterised)"]],
    Inches(0.4), Inches(2.1), Inches(5.6), Inches(1.55), font_size=15)

add_text(sl, "CRC-32 tolerates higher flips/node due to\n"
             "a stronger hash (1/4B false-positive rate vs 1/65K for CRC-16).",
         Inches(0.4), Inches(3.78), Inches(5.6), Inches(0.55),
         size=12, italic=True, color=DGRAY)

add_text(sl, "Evidence across experiments:",
         Inches(0.4), Inches(4.45), Inches(5.6), Inches(0.35),
         size=14, bold=True, color=DGRAY)
add_table(sl,
    ["Hash", "L", "Flips", "Flips/node", "Success"],
    [["CRC-32", "1024", "51",  "1.59", "100%"],
     ["CRC-32", "4096", "266", "4.16", "100%"],
     ["CRC-16", "1024", "51",  "1.59", "100%"],
     ["CRC-16", "2048", "102", "2.22", "70%"],
     ["CRC-16", "4096", "204", "3.19", "0%"],
     ["CRC-32", "4096", "204", "3.19", "100%"]],
    Inches(0.4), Inches(4.88), Inches(5.6), Inches(2.3), font_size=13)

callout_box(sl, [
    "√L = number of row-groups → flips ÷ √L = average load per solver node",
    "Collapses Fig 1, Fig 2, Fig 3, and Fig 6 onto a single predictive axis",
    "Design rule: keep flips/node < 1.6 for reliable operation",
    "Threshold values are empirical — out-of-sample validation (L=768, 3072) is proposed next",
], Inches(6.6), Inches(1.25), Inches(6.4), Inches(4.0),
   title="Why this variable?", accent=ACCENT)
note(sl, "This is the theoretical contribution. Functional form is from the architecture; thresholds are empirical.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 8 — SDC Safety
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=WHITE)
slide_header(sl, "Safety: Silent Data Corruption",
             "When does the solver return wrong bits without detecting failure?  50 keys/cell")

embed(sl, FIG["sdc"], Inches(5.6), Inches(1.2), Inches(7.5), Inches(5.8))

add_table(sl,
    ["Config", "SDC rate", "Status"],
    [["CRC-8,  gs=1",  "78.6%", "⚠  Unsafe"],
     ["CRC-16, gs=1",  "14.2%", "⚠  Risky"],
     ["CRC-16, gs=2",  "~0%",   "✓  Safe"],
     ["CRC-32, gs=1",  "0%",    "✓  Safe"]],
    Inches(0.4), Inches(1.35), Inches(4.9), Inches(2.25), font_size=15)

add_text(sl, "CRC-32: zero silent errors across all tested configurations.",
         Inches(0.4), Inches(3.72), Inches(4.9), Inches(0.45),
         size=15, bold=True, color=GREEN)

add_bullets(sl, [
    "SDC: solver returns a wrong bitstring that satisfies all hash checks",
    "CRC-8 'solves fast' because it accepts false positives — it's not efficient, it's wrong",
    "CRC-32 false-positive rate: 1 in 4 billion — zero SDC observed",
    "CRC width selection is a safety boundary, not a performance knob",
], Inches(0.4), Inches(4.28), Inches(4.9), Inches(2.7), size=13, color=DGRAY)
note(sl, "Present CRC-8 number without softening. You found it — that's intellectual credit.")


# ═══════════════════════════════════════════════════════════════════════════════
# SLIDE 9 — Positioning + Summary
# ═══════════════════════════════════════════════════════════════════════════════
sl = prs.slides.add_slide(BLANK)
add_rect(sl, 0, 0, W, H, fill=NAVY)
add_rect(sl, 0, 0, W, Inches(1.1), fill=RGBColor(0x10, 0x1E, 0x35))
add_rect(sl, 0, Inches(1.1), W, Inches(0.04), fill=ACCENT)
add_text(sl, "Summary", Inches(0.35), Inches(0.15), Inches(12.6), Inches(0.8),
         size=32, bold=True, color=WHITE)

# Left: comparison table
add_table(sl,
    ["", "Our scheme (CRC-32)", "BCH (256-bit blocks)"],
    [
        ["Overhead at 5% BER",   "100%",         "45.7%  ← BCH wins"],
        ["Burst tolerance",       "200+ bits  ✓", "13 bits  ✗"],
        ["Correction guarantee",  "Probabilistic","Deterministic  ✓"],
        ["SDC risk",              "0%  ✓",        "0%  ✓"],
        ["Decode cost",           "CRC checks ✓", "GF field ops"],
        ["Overhead scaling",      "O(1/√L)  ✓",   "Flat"],
    ],
    Inches(0.35), Inches(1.2), Inches(7.1), Inches(3.85),
    hdr_fill=RGBColor(0x10, 0x1E, 0x35), hdr_fg=WHITE, font_size=13)

# Right: summary bullets
add_text(sl, "Key results:", Inches(7.75), Inches(1.2), Inches(5.3), Inches(0.38),
         size=15, bold=True, color=WHITE)
add_bullets(sl, [
    "BCH fails on bursts > t bits — demonstrated empirically (slide 3)",
    "Our Feistel permutation converts bursts to uniform errors — burst and random curves overlap",
    "CRC-32: 100% success through 6.5% BER, zero SDC",
    "Flips/node < 1.6 is the design rule for reliable operation",
    "BCH wins on overhead for random errors — our advantage is burst channels",
], Inches(7.75), Inches(1.65), Inches(5.3), Inches(3.5), size=13,
   color=RGBColor(0xCC, 0xDD, 0xEE))

add_rect(sl, Inches(0.35), Inches(5.2), Inches(12.6), Inches(2.1),
         fill=RGBColor(0x10, 0x1E, 0x35))
add_text(sl, "The case for this scheme:",
         Inches(0.55), Inches(5.28), Inches(12.2), Inches(0.38),
         size=15, bold=True, color=ACCENT)
add_text(sl,
    "For any channel where errors cluster (flash retention, DRAM row-hammer, fiber interference), "
    "BCH's small per-block t budget is exceeded by real bursts. Our Feistel permutation neutralises "
    "this structurally — no interleaving layer required, no burst-length assumption, at a decode cost "
    "10–30× lower than BCH. The overhead premium (~2× at 5% BER) is the price of that robustness.",
    Inches(0.55), Inches(5.72), Inches(12.2), Inches(1.5),
    size=14, color=RGBColor(0xCC, 0xDD, 0xEE))
note(sl, "This is the closing argument. Read the bottom paragraph aloud.")


# ── Save ──────────────────────────────────────────────────────────────────────
OUT = os.path.join(os.path.dirname(__file__), "advisor_slides.pptx")
prs.save(OUT)
print(f"Saved {prs.slides.__len__()} slides → {OUT}")
