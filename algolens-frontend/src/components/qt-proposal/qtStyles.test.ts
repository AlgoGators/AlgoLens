//
// Colour contrast of the class tokens the QT panel is drawn with, in both
// themes. Presentation only, but a reader has to be able to read it:
//   - body text needs 4.5:1 (WCAG AA); the locked quantity, which is data, is
//     held to the same 4.5:1 (the earlier draft of this file asked 7:1; AA is the floor);
//   - the box around an editable quantity, and the focus ring, need 3:1 against
//     what is behind them (WCAG 1.4.11).
// Colours are read from the Tailwind theme file the build uses, so the numbers
// are the ones the browser draws (Tailwind 4 palette is OKLCH, not the v3 hex),
// and the tests read the class names the tokens emit: swapping a class for a
// paler one fails here.

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { qtStyles, type QtTone } from './qtStyles';

type Rgb = [number, number, number]; // gamma-encoded sRGB, 0..1
interface Paint { rgb: Rgb; alpha: number }

const themeCss = readFileSync(resolve(process.cwd(), 'node_modules/tailwindcss/theme.css'), 'utf8');
const clamp = (v: number) => Math.min(1, Math.max(0, v));
const encode = (v: number) => (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055);

function oklchToRgb(l: number, c: number, hue: number): Rgb {
  const a = c * Math.cos(hue * Math.PI / 180), b = c * Math.sin(hue * Math.PI / 180);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  return [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
  ].map(v => encode(clamp(v))) as Rgb;
}
/** A Tailwind colour by name ("amber-700", "white"), or null when the name is not a colour (e.g. "right", "sm", "2"). */
function themeColour(name: string): Rgb | null {
  const match = themeCss.match(new RegExp(`--color-${name}:\\s*(?:oklch\\(([\\d.]+)%\\s+([\\d.]+)\\s+([\\d.]+)\\)|#([0-9a-fA-F]{6}|[0-9a-fA-F]{3}))`));
  if (!match) return null;
  if (match[1]) return oklchToRgb(Number(match[1]) / 100, Number(match[2]), Number(match[3]));
  const hex = match[4].length === 3 ? [...match[4]].map(ch => ch + ch).join('') : match[4];
  return [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16) / 255) as Rgb;
}

const luminance = ([r, g, b]: Rgb) => {
  const lin = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
};
function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
const over = (paint: Paint, under: Rgb): Rgb => paint.rgb.map((v, i) => v * paint.alpha + under[i] * (1 - paint.alpha)) as Rgb;

/** Every colour utility in a class list: `hover:bg-amber-800` -> { variants:['hover'], util:'bg', paint }. */
function paints(classes: string) {
  const found: { variants: string[]; util: string; paint: Paint }[] = [];
  for (const token of classes.split(/\s+/).filter(Boolean)) {
    const parts = token.split(':');
    const body = parts.pop() as string;
    const match = body.match(/^(ring-offset|bg|text|border|ring)-([a-z]+(?:-\d+)?)(?:\/(\d+))?$/);
    const rgb = match ? themeColour(match[2]) : null;
    if (match && rgb) found.push({ variants: parts, util: match[1], paint: { rgb, alpha: match[3] ? Number(match[3]) / 100 : 1 } });
  }
  return found;
}
function pick(classes: string, util: string, variant: string | null = null): Paint {
  const hit = paints(classes).find(p => p.util === util && (variant === null ? p.variants.length === 0 : p.variants.includes(variant)));
  if (!hit) throw new Error(`no ${variant ? variant + ':' : ''}${util}- colour in: ${classes}`);
  return hit.paint;
}
const has = (classes: string, util: string, variant: string | null = null) => {
  try { pick(classes, util, variant); return true; } catch { return false; }
};

function atLeast(label: string, fg: Rgb, bg: Rgb, min: number) {
  const ratio = contrast(fg, bg);
  expect(ratio, `${label}: ${ratio.toFixed(2)}:1, needs ${min}:1`).toBeGreaterThanOrEqual(min);
}

const tones: QtTone[] = ['success', 'warning', 'danger', 'info', 'neutral'];

describe.each([false, true])('dark theme: %s', dark => {
  const ui = qtStyles(dark);
  const name = dark ? 'dark' : 'light';
  // What the panel is drawn on, and the card that sits on it (both derived from the tokens).
  const panel = pick(ui.panel, 'bg').rgb;
  const card = over(pick(ui.card, 'bg'), panel);
  const surfaces: [string, Rgb][] = [['panel', panel], ['card', card]];
  const bodyText = pick(ui.panel, 'text').rgb;

  describe('buttons', () => {
    const buttons = { btnPrimary: ui.btnPrimary, btnWarning: ui.btnWarning, btnSecondary: ui.btnSecondary, btnGhost: ui.btnGhost };
    for (const [key, classes] of Object.entries(buttons)) {
      const fg = pick(classes, 'text').rgb;
      it(`${key}: label is at least 4.5:1 at rest and under the pointer`, () => {
        for (const [where, surface] of surfaces) {
          const rest = has(classes, 'bg') ? over(pick(classes, 'bg'), surface) : surface;
          atLeast(`${name} ${key} rest on ${where}`, fg, rest, 4.5);
          atLeast(`${name} ${key} hover on ${where}`, fg, over(pick(classes, 'bg', 'hover'), surface), 4.5);
        }
      });
      it(`${key}: does not show a hover colour while disabled`, () => {
        expect(paints(classes).filter(p => p.variants.includes('hover')).every(p => p.variants.includes('enabled'))).toBe(true);
        expect(paints(classes).some(p => p.variants.includes('hover'))).toBe(true);
        expect(classes).toContain('disabled:cursor-not-allowed');
      });
    }
    it('draws the warning button in white on amber-700 or darker (the review asked for amber-700)', () => {
      expect(ui.btnWarning).toContain('text-white');
      expect(ui.btnWarning).toMatch(/\bbg-amber-(700|800|900)\b/);
      expect(ui.btnWarning).toMatch(/\bhover:bg-amber-(700|800|900)\b|\benabled:hover:bg-amber-(700|800|900)\b/);
    });
    it('keeps a focus ring that stands out (3:1) with an offset the colour of the surface behind it', () => {
      const ring = pick(ui.btnPrimary, 'ring', 'focus-visible').rgb;
      for (const [where, surface] of surfaces) atLeast(`${name} focus ring on ${where}`, ring, surface, 3);
      expect(pick(ui.btnPrimary, 'ring-offset', 'focus-visible').rgb).toEqual(panel);
    });
  });

  describe('tones (badges and callouts)', () => {
    it.each(tones)('%s text is at least 4.5:1 on its own tint over the panel and over a card', tone => {
      for (const [where, surface] of surfaces) {
        const bg = over(pick(ui.tone[tone], 'bg'), surface);
        atLeast(`${name} tone ${tone} on ${where}`, pick(ui.tone[tone], 'text').rgb, bg, 4.5);
      }
    });
    it('badges and callouts use the same tone tokens, and a badge wraps rather than overflowing', () => {
      for (const tone of tones) {
        expect(ui.badge(tone)).toContain(ui.tone[tone]);
        expect(ui.callout(tone)).toContain(ui.tone[tone]);
      }
      expect(ui.badge('info')).toContain('wrap-anywhere');
      expect(ui.badge('info')).toContain('max-w-full');
    });
  });

  describe('text', () => {
    it('muted text and notes are at least 4.5:1 on the panel, a card, a table header and a hovered row', () => {
      const muted = pick(ui.muted, 'text').rgb;
      for (const [where, surface] of surfaces) atLeast(`${name} muted on ${where}`, muted, surface, 4.5);
      atLeast(`${name} muted on table header`, muted, pick(ui.th, 'bg').rgb, 4.5);
      atLeast(`${name} muted on hovered row`, muted, over(pick(ui.tr, 'bg', 'hover'), panel), 4.5);
      expect(ui.note).toContain(ui.muted);
    });
    it('table header labels and body text are at least 4.5:1', () => {
      atLeast(`${name} th label`, pick(ui.th, 'text').rgb, pick(ui.th, 'bg').rgb, 4.5);
      atLeast(`${name} th right label`, pick(ui.thRight, 'text').rgb, pick(ui.thRight, 'bg').rgb, 4.5);
      atLeast(`${name} body text on hovered row`, bodyText, over(pick(ui.tr, 'bg', 'hover'), panel), 4.5);
      atLeast(`${name} body text on card`, bodyText, card, 4.5);
    });
    it('the change-from-MODEL colours are at least 4.5:1 on the panel and on a hovered row', () => {
      for (const kind of ['increase', 'decrease', 'invalid'] as const) {
        const fg = pick(ui.delta[kind], 'text').rgb;
        atLeast(`${name} delta ${kind} on panel`, fg, panel, 4.5);
        atLeast(`${name} delta ${kind} on hovered row`, fg, over(pick(ui.tr, 'bg', 'hover'), panel), 4.5);
      }
    });
  });

  describe('quantity box', () => {
    it('a locked quantity is at least 4.5:1 (WCAG AA) against its own box and still looks unavailable', () => {
      const locked = ui.input(true);
      atLeast(`${name} locked quantity`, pick(locked, "text").rgb, over(pick(locked, "bg"), card), 4.5);
      expect(locked).toContain('cursor-not-allowed');
    });
    it('an open quantity is at least 7:1 against its box, and its outline at least 3:1 against what surrounds it', () => {
      const open = ui.input(false);
      const box = over(pick(open, 'bg'), card);
      atLeast(`${name} open quantity`, pick(open, 'text').rgb, box, 7);
      const outline = pick(open, 'border').rgb;
      atLeast(`${name} open quantity outline on card`, outline, card, 3);
      atLeast(`${name} open quantity outline on edit cell`, outline, over({ rgb: themeColour('blue-500') as Rgb, alpha: 0.1 }, card), 3);
    });
    it('the box has a visible keyboard focus state', () => {
      for (const locked of [true, false]) expect(ui.input(locked)).toMatch(/focus:ring-2/);
    });
  });
});
