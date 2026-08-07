/** @odoo-module **/

// Mechanically transpiled from
// ateliera-app/apps/mobile/src/lib/label/phomemo-protocol.ts.

import { deviceDotsPerMm } from "./devices";
import { pack, padRows, rotateRaster, toBits } from "./raster";
const DEFAULT_PHOMEMO_SETTINGS = {
  density: 10,
  speed: 5,
  xoff: 0,
  dither: "threshold",
  feed: 32,
  continuous: false
};
function scale8(density) {
  return Math.max(1, Math.min(8, Math.round(density * 8 / 15)));
}
const HEAT_TIMES = [40, 60, 80, 100, 120, 140, 160, 200];
function heatTime(density) {
  return HEAT_TIMES[scale8(density) - 1];
}
function clamp(value, lo, hi) {
  return Math.max(lo, Math.min(hi, Math.round(value)));
}
const bytes = (...values) => Uint8Array.from(values);
const text = (value) => new TextEncoder().encode(value);
const CMD = {
  INIT: bytes(27, 64),
  FEED: (dots) => bytes(27, 74, dots & 255),
  DENSITY: (level) => bytes(29, 124, level),
  /** ESC 7: max dots, heat time, heat interval. */
  HEAT: (maxDots, heat, interval) => bytes(27, 55, maxDots, heat, interval),
  RASTER_HEADER: (widthBytes, heightLines) => bytes(
    29,
    118,
    48,
    0,
    widthBytes & 255,
    widthBytes >> 8 & 255,
    heightLines & 255,
    heightLines >> 8 & 255
  )
};
const M02_PREFIX = bytes(16, 255, 254, 1);
const M110 = {
  SPEED: (speed) => bytes(27, 78, 13, speed),
  DENSITY: (density) => bytes(27, 78, 4, density),
  /** 0x0a: die-cut labels with gaps. 0x0b: continuous. */
  MEDIA: (type) => bytes(31, 17, type),
  FOOTER: bytes(31, 240, 5, 0, 31, 240, 3, 0)
};
const M04 = {
  DENSITY: (level) => bytes(31, 17, 2, level),
  HEAT: (param) => bytes(31, 17, 55, param),
  INIT: bytes(31, 17, 11),
  COMPRESSION: (mode) => bytes(31, 17, 53, mode),
  FEED: bytes(27, 100, 2)
};
const D_SERIES = {
  /** ESC @ then GS v 0, in one write: the init is part of the header here. */
  HEADER: (widthBytes, rows) => bytes(
    27,
    64,
    29,
    118,
    48,
    0,
    widthBytes & 255,
    widthBytes >> 8 & 255,
    rows & 255,
    rows >> 8 & 255
  ),
  /** ESC d 0: print with gap detection, no feed. */
  END: bytes(27, 100, 0),
  /** Head to cutter on a D30, in dots at 203 dpi. */
  CUTTER_OFFSET: 56
};
const P12 = {
  /** soburi's sequence; each packet expects an answer before the next. */
  INIT: [
    bytes(31, 17, 56),
    bytes(31, 17, 17, 31, 17, 18, 31, 17, 9, 31, 17, 19),
    bytes(31, 17, 9),
    bytes(31, 17, 25, 31, 17, 17),
    bytes(31, 17, 25),
    bytes(31, 17, 7)
  ],
  HEADER: D_SERIES.HEADER,
  FEED: bytes(27, 100, 13)
};
function buildRaster(image, device, settings) {
  const bits = toBits(image, settings.dither);
  const widthBytes = device.rotated ? null : device.widthBytes;
  return pack(bits, image.width, image.height, {
    widthBytes,
    alignment: settings.align ?? device.alignment,
    xoff: settings.xoff
  });
}
function buildMSeries(raster, settings) {
  return [
    { bytes: CMD.INIT, pauseMs: 100 },
    { bytes: CMD.HEAT(7, heatTime(settings.density), 2), pauseMs: 30 },
    // The standard density command as well: some units honour one, some
    // the other, and neither is harmful where it is ignored.
    { bytes: CMD.DENSITY(scale8(settings.density)), pauseMs: 50 },
    { bytes: CMD.RASTER_HEADER(raster.widthBytes, raster.heightLines) },
    { bytes: raster.data, chunk: 128, pauseMs: 20, data: true },
    { bytes: new Uint8Array(0), pauseMs: 300 },
    { bytes: CMD.FEED(settings.feed), pauseMs: 800 }
  ];
}
function buildM02(raster, settings) {
  return [
    { bytes: M02_PREFIX, pauseMs: 50 },
    { bytes: CMD.INIT, pauseMs: 100 },
    { bytes: CMD.HEAT(7, heatTime(settings.density), 2), pauseMs: 30 },
    { bytes: CMD.RASTER_HEADER(raster.widthBytes, raster.heightLines) },
    { bytes: raster.data, chunk: 128, pauseMs: 20, data: true },
    { bytes: new Uint8Array(0), pauseMs: 300 },
    // Continuous paper: feed only enough to clear the head, or the roll is
    // eaten a label at a time.
    { bytes: CMD.FEED(8), pauseMs: 500 }
  ];
}
function buildM04(raster, settings) {
  const d8 = scale8(settings.density);
  const steps = [
    { bytes: M04.DENSITY(clamp(d8 / 8 * 15, 0, 15)), pauseMs: 30 },
    { bytes: M04.HEAT(clamp(100 + (d8 - 1) * 50 / 3, 0, 255)), pauseMs: 30 },
    { bytes: M04.INIT, pauseMs: 30 },
    // Raw rather than LZO: the firmware takes both and this app has no
    // reason to spend the compression.
    { bytes: M04.COMPRESSION(0), pauseMs: 30 },
    { bytes: CMD.RASTER_HEADER(raster.widthBytes, raster.heightLines) },
    { bytes: raster.data, chunk: 256, pauseMs: 20, data: true },
    { bytes: new Uint8Array(0), pauseMs: 300 }
  ];
  const feeds = Math.max(1, Math.round(settings.feed / 16));
  for (let i = 0; i < feeds; i++) steps.push({ bytes: M04.FEED, pauseMs: 30 });
  steps.push({ bytes: new Uint8Array(0), pauseMs: 500 });
  return steps;
}
function buildM110(raster, settings) {
  return [
    { bytes: M110.SPEED(clamp(settings.speed, 1, 15)), pauseMs: 30 },
    { bytes: M110.DENSITY(clamp(settings.density, 1, 15)), pauseMs: 30 },
    { bytes: M110.MEDIA(settings.continuous ? 11 : 10), pauseMs: 30 },
    { bytes: CMD.RASTER_HEADER(raster.widthBytes, raster.heightLines) },
    { bytes: raster.data, chunk: 128, pauseMs: 20, data: true },
    { bytes: new Uint8Array(0), pauseMs: 300 },
    { bytes: M110.FOOTER, pauseMs: 500 }
  ];
}
function buildDSeries(raster, settings) {
  let turned = rotateRaster(raster, "cw");
  if (settings.continuous && settings.feed > 0) {
    turned = padRows(turned, D_SERIES.CUTTER_OFFSET + settings.feed);
  }
  return [
    { bytes: CMD.HEAT(7, heatTime(settings.density), 2), pauseMs: 30 },
    { bytes: M110.MEDIA(settings.continuous ? 11 : 10), pauseMs: 30 },
    { bytes: D_SERIES.HEADER(turned.widthBytes, turned.heightLines) },
    { bytes: turned.data, chunk: 128, pauseMs: 20, data: true },
    { bytes: new Uint8Array(0), pauseMs: 100 },
    { bytes: D_SERIES.END }
  ];
}
function buildP12(raster) {
  const turned = rotateRaster(raster, "cw");
  const steps = P12.INIT.map((packet) => ({
    bytes: packet,
    awaitReply: true,
    pauseMs: 100
  }));
  steps.push(
    { bytes: P12.HEADER(turned.widthBytes, turned.heightLines) },
    { bytes: turned.data, chunk: 128, pauseMs: 20, data: true },
    { bytes: new Uint8Array(0), pauseMs: 100 },
    { bytes: P12.FEED, pauseMs: 50 },
    { bytes: P12.FEED }
  );
  return steps;
}
function buildTspl(raster, device, settings) {
  const dpmm = deviceDotsPerMm(device);
  const widthMm = Math.round(raster.widthBytes * 8 / dpmm);
  const heightMm = Math.round(raster.heightLines / dpmm);
  const inverted = new Uint8Array(raster.data.length);
  for (let i = 0; i < inverted.length; i++) inverted[i] = raster.data[i] ^ 255;
  return [
    { bytes: text(`SIZE ${widthMm} mm, ${heightMm} mm\r
`), pauseMs: 50 },
    { bytes: text(`GAP ${settings.continuous ? 0 : 3} mm, 0 mm\r
`), pauseMs: 50 },
    { bytes: text("OFFSET -3 mm\r\n"), pauseMs: 50 },
    { bytes: text(`DENSITY ${clamp(scale8(settings.density) / 8 * 15, 0, 15)}\r
`), pauseMs: 50 },
    { bytes: text("SPEED 4\r\n"), pauseMs: 50 },
    { bytes: text("DIRECTION 0\r\n"), pauseMs: 50 },
    { bytes: text("CLS\r\n"), pauseMs: 50 },
    { bytes: text(`BITMAP 0,0,${raster.widthBytes},${raster.heightLines},0,`) },
    { bytes: inverted, chunk: 512, pauseMs: 10, data: true },
    { bytes: text("\r\n"), pauseMs: 50 },
    { bytes: text("PRINT 1\r\n"), pauseMs: 100 }
  ];
}
function buildJob(image, device, settings) {
  const raster = buildRaster(image, device, settings);
  const steps = (() => {
    switch (device.protocol) {
      case "m02":
        return buildM02(raster, settings);
      case "m04":
        return buildM04(raster, settings);
      case "m110":
        return buildM110(raster, settings);
      case "d-series":
        return buildDSeries(raster, settings);
      case "p12":
        return buildP12(raster);
      case "tspl":
        return buildTspl(raster, device, settings);
      case "m-series":
        return buildMSeries(raster, settings);
    }
  })();
  return {
    steps: steps.filter((step) => step.bytes.length > 0 || step.pauseMs),
    widthBytes: raster.widthBytes,
    heightLines: raster.heightLines
  };
}
function jobBytes(job) {
  return job.steps.reduce((n, step) => n + step.bytes.length, 0);
}
function jobInk(job) {
  let set = 0;
  let total = 0;
  for (const step of job.steps) {
    if (!step.data) continue;
    for (const byte of step.bytes) {
      total += 8;
      for (let b = byte; b; b >>= 1) set += b & 1;
    }
  }
  return total === 0 ? 0 : set / total;
}
function testPattern(device, heightLines = 160) {
  const width = device.widthBytes === null ? 96 : device.widthBytes * 8;
  const data = new Uint8ClampedArray(width * heightLines * 4).fill(255);
  const band = Math.max(1, Math.round(heightLines / 8));
  for (let y = 0; y < heightLines; y++) {
    if (Math.floor(y / band) % 2 !== 0) continue;
    for (let x = 8; x < width - 8; x++) {
      const i = (y * width + x) * 4;
      data[i] = 0;
      data[i + 1] = 0;
      data[i + 2] = 0;
    }
  }
  return { data, width, height: heightLines, colorSpace: "srgb" };
}
export {
  DEFAULT_PHOMEMO_SETTINGS,
  buildJob,
  jobBytes,
  jobInk,
  testPattern
};
