/**
 * Generate the PWA icon set into `public/icons/`.
 *
 * **Why generated rather than committed as opaque binaries.** A PNG checked into a public repository
 * with no way to reproduce it is a small unreproducible input (DP-11): the next person who needs a
 * 384px variant, or the same mark in a changed accent colour, has nothing to work from. This script
 * is the source; the PNGs are its build output, committed so a clone can build without running it.
 *
 * **Why a hand-rolled PNG encoder.** The image is flat colour with hard edges, so encoding it needs
 * only `zlib`, which is in the standard library. Adding an image toolchain to draw two shapes would
 * be a dependency bought for one file (Invariant 3 is about paid services, but the same instinct
 * applies to weight on a project maintained by one person).
 *
 * Colours come from `tokens.css` — read from it, never restated here, for the same reason no other
 * file in the web app restates a colour.
 *
 * Run:  node scripts/make-icons.mjs
 */
import { deflateSync } from "node:zlib";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..");
const OUT = resolve(ROOT, "public/icons");

// --- the palette, read from the single place colour is allowed to live ---------------------------

const tokens = readFileSync(resolve(ROOT, "src/tokens.css"), "utf8");
const lightRoot = /^:root \{([\s\S]*?)\n\}/m.exec(tokens)[1];
const token = (name) => {
  const found = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`).exec(lightRoot);
  if (!found) throw new Error(`tokens.css has no ${name}`);
  return found[1];
};

/**
 * The accent and the colour that is *defined* as the one legible on it. Picking any other pair would
 * be choosing two colours by eye and hoping; this pair is held to 4.5:1 by `theme/contrast.test.ts`,
 * so the mark cannot quietly stop reading against its field.
 */
const FIELD = token("--accent");
const MARK = token("--on-accent");
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

// --- PNG encoding --------------------------------------------------------------------------------

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(buffer) {
  let c = 0xffffffff;
  for (const byte of buffer) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

/** `pixels` is RGBA, row-major, length 4·size·size. */
function encodePng(size, pixels) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // colour type: RGBA
  // 10, 11, 12 stay zero: deflate, adaptive filtering, no interlace.

  // Each scanline is prefixed with its filter type. Filter 0 (none) costs a few bytes on an image
  // this flat and keeps the encoder to something one can read in a sitting.
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y += 1) {
    const at = y * (size * 4 + 1);
    raw[at] = 0;
    pixels.copy(raw, at + 1, y * size * 4, (y + 1) * size * 4);
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// --- the mark ------------------------------------------------------------------------------------

/** Distance from a point to a line segment, used to draw the chevron with soft edges. */
function distanceToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/**
 * Draw the icon.
 *
 * `inset` is the fraction of the canvas the mark is pulled in by. A maskable icon may be cropped to
 * a circle inscribed in the middle 80%, so its mark is drawn smaller; the `any` icon uses the space.
 */
function draw(size, { inset, rounded }) {
  const pixels = Buffer.alloc(size * size * 4);
  const [fr, fg, fb] = rgb(FIELD);
  const [mr, mg, mb] = rgb(MARK);

  const radius = size * 0.22; // corner radius for the `any` icon
  const c = size / 2;
  const scale = size * (1 - inset * 2);

  // An upward chevron: the recommendation this app exists to make. Two segments, in canvas units
  // relative to the centre.
  const arm = scale * 0.30;
  const rise = scale * 0.20;
  const apexY = c - rise * 0.9;
  const footY = c + rise * 0.9;
  const stroke = scale * 0.085;

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const px = x + 0.5;
      const py = y + 0.5;

      // --- the field, with rounded corners on the `any` icon and full bleed on the maskable one ---
      let fieldAlpha = 1;
      if (rounded) {
        const qx = Math.abs(px - c) - (size / 2 - radius);
        const qy = Math.abs(py - c) - (size / 2 - radius);
        if (qx > 0 && qy > 0) {
          // Outside the straight edges in both axes: distance to the corner arc decides.
          fieldAlpha = Math.max(0, Math.min(1, radius - Math.hypot(qx, qy) + 0.5));
        }
      }

      // --- the chevron ---
      const d = Math.min(
        distanceToSegment(px, py, c - arm, footY, c, apexY),
        distanceToSegment(px, py, c, apexY, c + arm, footY),
      );
      const markAlpha = Math.max(0, Math.min(1, stroke / 2 - d + 0.5));

      const r = Math.round(fr + (mr - fr) * markAlpha);
      const g = Math.round(fg + (mg - fg) * markAlpha);
      const b = Math.round(fb + (mb - fb) * markAlpha);

      const at = (y * size + x) * 4;
      pixels[at] = r;
      pixels[at + 1] = g;
      pixels[at + 2] = b;
      pixels[at + 3] = Math.round(fieldAlpha * 255);
    }
  }
  return pixels;
}

// --- outputs -------------------------------------------------------------------------------------

mkdirSync(OUT, { recursive: true });

const OUTPUTS = [
  // 192 and 512 are what Chromium checks for installability; the maskable variant is what keeps
  // Android from putting a rounded square inside another rounded square.
  { file: "icon-192.png", size: 192, inset: 0.06, rounded: true },
  { file: "icon-512.png", size: 512, inset: 0.06, rounded: true },
  { file: "icon-maskable-512.png", size: 512, inset: 0.19, rounded: false },
  // iOS ignores the manifest's icons and reads `apple-touch-icon`, which must not be transparent.
  { file: "apple-touch-icon.png", size: 180, inset: 0.06, rounded: false },
];

for (const { file, size, inset, rounded } of OUTPUTS) {
  writeFileSync(resolve(OUT, file), encodePng(size, draw(size, { inset, rounded })));
  console.log(`wrote icons/${file} (${size}x${size})`);
}

// A vector favicon as well, because a browser tab renders at 16px and a downsampled PNG chevron at
// that size is mud.
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="FPL DOF">
  <rect width="64" height="64" rx="14" fill="${FIELD}"/>
  <path d="M15 41 L32 23 L49 41" fill="none" stroke="${MARK}" stroke-width="7"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>
`;
writeFileSync(resolve(OUT, "icon.svg"), svg);
console.log("wrote icons/icon.svg");
