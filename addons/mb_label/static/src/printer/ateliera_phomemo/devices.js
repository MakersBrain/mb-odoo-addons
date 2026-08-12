/** @odoo-module **/

// Mechanically transpiled from ateliera-app/apps/mobile/src/lib/label/devices.ts.
// Keep this table synchronized with Ateliera; it is the shared Phomemo model source.
//
// Two fields of the upstream table are dropped here on purpose: `group` and
// `description` hold French prose, nothing in this addon reads either, and a
// French literal in source is exactly what the translation catalogues exist to
// prevent. If a device ever needs a description on screen, add it as an English
// string wrapped in `_t()` at the point of use rather than restoring the field —
// re-transpiling must not bring them back.

const BUILTIN_DEVICES = [
  {
    id: "p12",
    name: "P12 / P12 Pro",
    protocol: "p12",
    widthBytes: 12,
    dpi: 203,
    alignment: "center",
    rotated: true,
    tape: true,
    tapeWidths: [12],
    defaultTapeWidth: 12,
    namePatterns: ["P12 PRO", "P12PRO", "P12"],
    labelPresets: "tape",
    builtin: true
  },
  {
    id: "a30",
    name: "A30",
    protocol: "p12",
    widthBytes: 15,
    dpi: 203,
    alignment: "center",
    rotated: true,
    tape: true,
    tapeWidths: [12, 14, 15],
    defaultTapeWidth: 15,
    namePatterns: ["A30"],
    labelPresets: "tape",
    builtin: true
  },
  {
    id: "m02",
    name: "M02 / M02S / M02X",
    protocol: "m02",
    widthBytes: 48,
    dpi: 203,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["M02X", "M02S", "M02"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m02-pro",
    name: "M02 Pro",
    protocol: "m02",
    widthBytes: 78,
    dpi: 300,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["M02 PRO", "M02PRO"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m03",
    name: "M03",
    protocol: "m-series",
    widthBytes: 54,
    dpi: 203,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["M03"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "t02",
    name: "T02",
    protocol: "m-series",
    widthBytes: 48,
    dpi: 203,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["T02"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m04s-53",
    name: "M04S - papier 53 mm",
    protocol: "m04",
    widthBytes: 75,
    dpi: 300,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["M04A", "M04"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m04s-80",
    name: "M04S - papier 80 mm",
    protocol: "m04",
    widthBytes: 112,
    dpi: 300,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: [],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m04s-110",
    name: "M04S - papier 110 mm",
    protocol: "m04",
    widthBytes: 154,
    dpi: 300,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: [],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m110",
    name: "M110 / M120",
    protocol: "m110",
    widthBytes: 48,
    dpi: 203,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    // `Q1…` is a unit advertising its serial rather than a model name -
    // Q199G4130440005 is one, and it prints correctly as an M110. phomymo's
    // own picker filters on a bare `Q` for the same reason and calls it an
    // M110S; that variant differs only in where the roll sits, so a label
    // that comes out shifted wants `m110s` chosen by hand rather than a
    // different pattern here. Sorted by length, `Q30`/`Q30S` still reach the
    // D-series ahead of this.
    namePatterns: ["M110", "M120", "Q1"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m110s",
    name: "M110S",
    protocol: "m110",
    widthBytes: 48,
    dpi: 203,
    alignment: "right",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: [],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m200",
    name: "M200",
    protocol: "m-series",
    widthBytes: 76,
    dpi: 203,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["M200"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m250",
    name: "M250",
    protocol: "m-series",
    widthBytes: 72,
    dpi: 203,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["M250"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m220",
    name: "M220",
    protocol: "m-series",
    widthBytes: 72,
    dpi: 203,
    alignment: "right",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["M220"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m221",
    name: "M221",
    protocol: "m-series",
    widthBytes: 72,
    dpi: 203,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["M221"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "m260",
    name: "M260",
    protocol: "m-series",
    widthBytes: 72,
    dpi: 203,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["M260"],
    labelPresets: "m-series",
    builtin: true
  },
  {
    id: "pm241",
    name: "PM-241-BT",
    protocol: "tspl",
    widthBytes: 102,
    dpi: 203,
    alignment: "center",
    rotated: false,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    namePatterns: ["PM-241", "PM241", "PM 241"],
    labelPresets: "pm241",
    builtin: true
  },
  {
    id: "d-series",
    name: "D30 / D35 / D50 / D110 / Q30 / Q30S",
    protocol: "d-series",
    widthBytes: null,
    dpi: 203,
    alignment: "center",
    rotated: true,
    tape: false,
    tapeWidths: null,
    defaultTapeWidth: null,
    // The bare `D` is phomymo's catch-all for the D-variants it does not
    // list; sorted last by length, it only fires when nothing else matched.
    namePatterns: ["D110", "D30", "D35", "D50", "Q30S", "Q30", "D"],
    labelPresets: "d-series",
    builtin: true
  }
];
const FALLBACK_DEVICE_ID = "m110";
const M_SERIES_PRESETS = [
  { name: "12 x 40 mm", widthMm: 12, heightMm: 40 },
  { name: "15 x 30 mm", widthMm: 15, heightMm: 30 },
  { name: "20 x 30 mm", widthMm: 20, heightMm: 30 },
  { name: "25 x 50 mm", widthMm: 25, heightMm: 50 },
  { name: "30 x 20 mm", widthMm: 30, heightMm: 20 },
  { name: "30 x 40 mm", widthMm: 30, heightMm: 40 },
  { name: "40 x 30 mm", widthMm: 40, heightMm: 30 },
  { name: "40 x 60 mm", widthMm: 40, heightMm: 60 },
  { name: "50 x 25 mm", widthMm: 50, heightMm: 25 },
  { name: "50 x 30 mm", widthMm: 50, heightMm: 30 },
  { name: "50 x 80 mm", widthMm: 50, heightMm: 80 },
  { name: "60 x 40 mm", widthMm: 60, heightMm: 40 },
  { name: "Rond 20 mm", widthMm: 20, heightMm: 20, round: true },
  { name: "Rond 30 mm", widthMm: 30, heightMm: 30, round: true },
  { name: "Rond 40 mm", widthMm: 40, heightMm: 40, round: true },
  { name: "Rond 50 mm", widthMm: 50, heightMm: 50, round: true }
];
const D_SERIES_PRESETS = [
  { name: "40 x 12 mm", widthMm: 40, heightMm: 12 },
  { name: "30 x 12 mm", widthMm: 30, heightMm: 12 },
  { name: "22 x 12 mm", widthMm: 22, heightMm: 12 },
  { name: "12 x 12 mm", widthMm: 12, heightMm: 12 },
  { name: "30 x 14 mm", widthMm: 30, heightMm: 14 },
  { name: "22 x 14 mm", widthMm: 22, heightMm: 14 },
  { name: "40 x 15 mm", widthMm: 40, heightMm: 15 },
  { name: "30 x 15 mm", widthMm: 30, heightMm: 15 },
  { name: "40 x 12 mm continu", widthMm: 40, heightMm: 12, continuous: true },
  { name: "30 x 12 mm continu", widthMm: 30, heightMm: 12, continuous: true },
  { name: "22 x 12 mm continu", widthMm: 22, heightMm: 12, continuous: true },
  { name: "40 x 15 mm continu", widthMm: 40, heightMm: 15, continuous: true },
  { name: "30 x 15 mm continu", widthMm: 30, heightMm: 15, continuous: true },
  { name: "Rond 14 mm", widthMm: 14, heightMm: 14, round: true }
];
const TAPE_PRESETS = [
  { name: "40 x 12 mm", widthMm: 40, heightMm: 12, tapeWidth: 12, continuous: true },
  { name: "30 x 12 mm", widthMm: 30, heightMm: 12, tapeWidth: 12, continuous: true },
  { name: "22 x 12 mm", widthMm: 22, heightMm: 12, tapeWidth: 12, continuous: true },
  { name: "12 x 12 mm", widthMm: 12, heightMm: 12, tapeWidth: 12, continuous: true },
  { name: "40 x 14 mm", widthMm: 40, heightMm: 14, tapeWidth: 14, continuous: true },
  { name: "30 x 14 mm", widthMm: 30, heightMm: 14, tapeWidth: 14, continuous: true },
  { name: "22 x 14 mm", widthMm: 22, heightMm: 14, tapeWidth: 14, continuous: true },
  { name: "14 x 14 mm", widthMm: 14, heightMm: 14, tapeWidth: 14, continuous: true },
  { name: "40 x 15 mm", widthMm: 40, heightMm: 15, tapeWidth: 15, continuous: true },
  { name: "30 x 15 mm", widthMm: 30, heightMm: 15, tapeWidth: 15, continuous: true },
  { name: "22 x 15 mm", widthMm: 22, heightMm: 15, tapeWidth: 15, continuous: true },
  { name: "15 x 15 mm", widthMm: 15, heightMm: 15, tapeWidth: 15, continuous: true }
];
const PM241_PRESETS = [
  { name: '102 x 152 mm (4x6")', widthMm: 102, heightMm: 152 },
  { name: '102 x 102 mm (4x4")', widthMm: 102, heightMm: 102 },
  { name: '102 x 76 mm (4x3")', widthMm: 102, heightMm: 76 },
  { name: '102 x 51 mm (4x2")', widthMm: 102, heightMm: 51 },
  { name: "100 x 150 mm", widthMm: 100, heightMm: 150 },
  { name: "100 x 100 mm", widthMm: 100, heightMm: 100 }
];
const PRESETS = {
  "m-series": M_SERIES_PRESETS,
  "d-series": D_SERIES_PRESETS,
  tape: TAPE_PRESETS,
  pm241: PM241_PRESETS
};
function presetsFor(device) {
  return PRESETS[device.labelPresets] ?? M_SERIES_PRESETS;
}
const CUSTOM_KEY = "label-phomemo-devices";
function customDevices() {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(CUSTOM_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
function allDevices() {
  const custom = customDevices();
  const overridden = new Set(custom.map((d) => d.id));
  return [...BUILTIN_DEVICES.filter((d) => !overridden.has(d.id)), ...custom];
}
function deviceById(id) {
  return allDevices().find((d) => d.id === id) ?? null;
}
function saveCustomDevice(device) {
  const custom = customDevices();
  const saved = { ...device, builtin: false };
  const index = custom.findIndex((d) => d.id === device.id);
  if (index >= 0) custom[index] = saved;
  else custom.push(saved);
  localStorage.setItem(CUSTOM_KEY, JSON.stringify(custom));
}
function deleteCustomDevice(id) {
  const left = customDevices().filter((d) => d.id !== id);
  localStorage.setItem(CUSTOM_KEY, JSON.stringify(left));
}
function isBuiltinDevice(id) {
  return BUILTIN_DEVICES.some((d) => d.id === id);
}
function isOverridden(id) {
  return isBuiltinDevice(id) && customDevices().some((d) => d.id === id);
}
function detectDevice(bleName) {
  if (!bleName) return null;
  const name = bleName.toUpperCase();
  const devices = allDevices();
  const patterns = [];
  for (const device of [...devices.filter((d) => !d.builtin), ...devices.filter((d) => d.builtin)]) {
    for (const pattern of device.namePatterns ?? []) {
      patterns.push({ pattern: pattern.toUpperCase(), device });
    }
  }
  patterns.sort((a, b) => b.pattern.length - a.pattern.length);
  return patterns.find(({ pattern }) => name.startsWith(pattern))?.device ?? null;
}
function resolveDevice(modelId, bleName) {
  if (modelId && modelId !== "auto") {
    const chosen = deviceById(modelId);
    if (chosen) return chosen;
  }
  return detectDevice(bleName) ?? deviceById(FALLBACK_DEVICE_ID) ?? BUILTIN_DEVICES[0];
}
function deviceDotsPerMm(device) {
  return device.dpi === 203 ? 8 : device.dpi / 25.4;
}
function headDots(device) {
  return device.widthBytes === null ? null : device.widthBytes * 8;
}
function headWidthMm(device) {
  const dots = headDots(device);
  return dots === null ? null : dots / deviceDotsPerMm(device);
}
function reachableOverBle(device) {
  return device.protocol !== "tspl";
}
export {
  BUILTIN_DEVICES,
  FALLBACK_DEVICE_ID,
  allDevices,
  customDevices,
  deleteCustomDevice,
  detectDevice,
  deviceById,
  deviceDotsPerMm,
  headDots,
  headWidthMm,
  isBuiltinDevice,
  isOverridden,
  presetsFor,
  reachableOverBle,
  resolveDevice,
  saveCustomDevice
};
