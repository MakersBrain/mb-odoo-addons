/** @odoo-module **/

// Mechanically transpiled from mb-app/apps/mobile/src/lib/label/raster.ts.
//
// Upstream's `DITHER_LABELS` map is dropped here on purpose: it holds French
// prose, nothing in this addon imports it, and the dither labels users actually
// see live in device_print.js where they are wrapped in `_t()`. Re-transpiling
// must not bring it back.

const BLACK_LEVEL = 160;
function toGrayscale(image) {
  const { data, width, height } = image;
  const grey = new Float32Array(width * height);
  for (let i = 0, p = 0; p < grey.length; i += 4, p++) {
    grey[p] = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
  }
  return grey;
}
function thresholdDither(grey, level) {
  const out = new Uint8Array(grey.length);
  for (let i = 0; i < grey.length; i++) out[i] = grey[i] < level ? 1 : 0;
  return out;
}
function floydSteinbergDither(grey, width, height) {
  const px = new Float32Array(grey);
  const out = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      const old = px[i];
      const next = old < 128 ? 0 : 255;
      out[i] = next === 0 ? 1 : 0;
      const error = old - next;
      if (x + 1 < width) px[i + 1] += error * 7 / 16;
      if (y + 1 < height) {
        if (x > 0) px[(y + 1) * width + x - 1] += error * 3 / 16;
        px[(y + 1) * width + x] += error * 5 / 16;
        if (x + 1 < width) px[(y + 1) * width + x + 1] += error * 1 / 16;
      }
    }
  }
  return out;
}
function atkinsonDither(grey, width, height) {
  const px = new Float32Array(grey);
  const out = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      const old = px[i];
      const next = old < 128 ? 0 : 255;
      out[i] = next === 0 ? 1 : 0;
      const error = (old - next) / 8;
      if (x + 1 < width) px[i + 1] += error;
      if (x + 2 < width) px[i + 2] += error;
      if (y + 1 < height) {
        if (x > 0) px[(y + 1) * width + x - 1] += error;
        px[(y + 1) * width + x] += error;
        if (x + 1 < width) px[(y + 1) * width + x + 1] += error;
      }
      if (y + 2 < height) px[(y + 2) * width + x] += error;
    }
  }
  return out;
}
const BAYER = [
  0,
  32,
  8,
  40,
  2,
  34,
  10,
  42,
  48,
  16,
  56,
  24,
  50,
  18,
  58,
  26,
  12,
  44,
  4,
  36,
  14,
  46,
  6,
  38,
  60,
  28,
  52,
  20,
  62,
  30,
  54,
  22,
  3,
  35,
  11,
  43,
  1,
  33,
  9,
  41,
  51,
  19,
  59,
  27,
  49,
  17,
  57,
  25,
  15,
  47,
  7,
  39,
  13,
  45,
  5,
  37,
  63,
  31,
  55,
  23,
  61,
  29,
  53,
  21
];
function orderedDither(grey, width, height) {
  const out = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      const level = BAYER[y % 8 * 8 + x % 8] / 64 * 255;
      out[i] = grey[i] < level ? 1 : 0;
    }
  }
  return out;
}
function toBits(image, mode, level = BLACK_LEVEL) {
  const grey = toGrayscale(image);
  const { width, height } = image;
  switch (mode) {
    case "threshold":
      return thresholdDither(grey, level);
    case "atkinson":
      return atkinsonDither(grey, width, height);
    case "ordered":
      return orderedDither(grey, width, height);
    case "floyd-steinberg":
      return floydSteinbergDither(grey, width, height);
  }
}
function pack(bits, width, height, options) {
  const widthBytes = options.widthBytes ?? Math.ceil(width / 8);
  const headDots = widthBytes * 8;
  const base = options.alignment === "center" ? Math.floor((headDots - width) / 2) : options.alignment === "right" ? headDots - width : 0;
  const lo = Math.min(0, headDots - width);
  const hi = Math.max(0, headDots - width);
  const left = Math.min(hi, Math.max(lo, base + (options.xoff ?? 0)));
  const data = new Uint8Array(widthBytes * height);
  for (let y = 0; y < height; y++) {
    const row = y * widthBytes;
    for (let x = 0; x < width; x++) {
      if (bits[y * width + x] !== 1) continue;
      const dot = left + x;
      if (dot < 0 || dot >= headDots) continue;
      data[row + (dot >> 3)] |= 128 >> (dot & 7);
    }
  }
  return { data, widthBytes, heightLines: height };
}
function rotateRaster(raster, direction) {
  const { data, widthBytes, heightLines } = raster;
  const srcWidth = widthBytes * 8;
  const dstWidth = heightLines;
  const dstHeight = srcWidth;
  const dstWidthBytes = Math.ceil(dstWidth / 8);
  const out = new Uint8Array(dstWidthBytes * dstHeight);
  for (let y = 0; y < heightLines; y++) {
    for (let x = 0; x < srcWidth; x++) {
      const bit = data[y * widthBytes + (x >> 3)] >> 7 - (x & 7) & 1;
      if (!bit) continue;
      const dstX = direction === "cw" ? heightLines - 1 - y : y;
      const dstY = direction === "cw" ? x : srcWidth - 1 - x;
      out[dstY * dstWidthBytes + (dstX >> 3)] |= 128 >> (dstX & 7);
    }
  }
  return { data: out, widthBytes: dstWidthBytes, heightLines: dstHeight };
}
function padRows(raster, rows) {
  if (rows <= 0) return raster;
  const data = new Uint8Array(raster.data.length + rows * raster.widthBytes);
  data.set(raster.data);
  return { data, widthBytes: raster.widthBytes, heightLines: raster.heightLines + rows };
}
export {
  BLACK_LEVEL,
  pack,
  padRows,
  rotateRaster,
  toBits
};
