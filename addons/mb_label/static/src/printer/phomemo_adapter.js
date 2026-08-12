/** @odoo-module **/

// Odoo shell around the exact browser print path used by Ateliera:
// phomymo/ble.js + phomymo/printer.js + phomymo/raster.js. Do not replace the
// transport or re-chunk its writes here; that was the source of the M110
// regression this port is intended to avoid.

import { _t } from "@web/core/l10n/translation";
import { loadRaster } from "./raster";
import { registerPrinterAdapter } from "./printer_registry";
import { BLETransport } from "./phomymo/ble";
import {
    getPrinterAlignment,
    getPrinterWidthBytes,
    isRotatedPrinter,
    loadPrinterDefinitions,
    print,
} from "./phomymo/printer";
import { _pixelsToRaster } from "./phomymo/raster";
import {
    allDevices,
    headWidthMm,
    reachableOverBle,
    resolveDevice,
} from "./ateliera_phomemo/devices";

const SETTINGS_KEY = "mb_label.phomemo.settings.v3";
const DEFAULT_SETTINGS = {
    model: "auto",
    density: 10,
    speed: 5,
    align: undefined,
    dither: "threshold",
    feed: 32,
    continuous: false,
};
const DITHER_MODES = new Set(["threshold", "floyd-steinberg", "atkinson", "ordered"]);

function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, Math.round(Number(value))));
}

export function normalizePhomemoSettings(settings = {}) {
    return {
        model: String(settings.model || DEFAULT_SETTINGS.model),
        density: clamp(settings.density ?? DEFAULT_SETTINGS.density, 1, 15),
        speed: clamp(settings.speed ?? DEFAULT_SETTINGS.speed, 1, 15),
        align: ["left", "center", "right"].includes(settings.align)
            ? settings.align : undefined,
        dither: DITHER_MODES.has(settings.dither) ? settings.dither : DEFAULT_SETTINGS.dither,
        feed: clamp(settings.feed ?? DEFAULT_SETTINGS.feed, 0, 255),
        continuous: Boolean(settings.continuous),
    };
}

export function loadPhomemoSettings(storage = globalThis.localStorage) {
    try {
        return normalizePhomemoSettings(JSON.parse(storage.getItem(SETTINGS_KEY) || "{}"));
    } catch {
        return normalizePhomemoSettings();
    }
}

export function savePhomemoSettings(settings, storage = globalThis.localStorage) {
    const normalized = normalizePhomemoSettings(settings);
    try {
        storage.setItem(SETTINGS_KEY, JSON.stringify(normalized));
    } catch {
        // Printing remains available when browser storage is blocked.
    }
    return normalized;
}

export function phomemoModels() {
    return allDevices().map((device) => ({
        id: device.id,
        name: device.name,
        protocol: device.protocol,
        dpi: device.dpi,
        head_mm: headWidthMm(device),
        alignment: device.alignment,
        rotated: device.rotated,
        ble: reachableOverBle(device),
    }));
}

let definitions;
function definitionsReady() {
    definitions ??= loadPrinterDefinitions();
    return definitions;
}

function transport() {
    return BLETransport.getShared();
}

async function connectedTransport(forceChooser = false) {
    await definitionsReady();
    const link = transport();
    if (forceChooser && link.isConnected()) await link.disconnect();
    if (!link.isConnected()) await link.connect({ showAllDevices: forceChooser });
    return link;
}

function toDensity8(density) {
    return Math.max(1, Math.min(8, Math.round((density * 8) / 15)));
}

export function assertRasterFitsDevice(image, device) {
    if (device.widthBytes === null) return;
    const usedDots = device.rotated ? image.height : image.width;
    const availableDots = device.widthBytes * 8;
    if (usedDots > availableDots) {
        throw new Error(_t(
            "The selected paper uses %(used)s dots across the print head, but %(device)s has %(available)s. Select the correct model or paper size.",
            { used: usedDots, device: device.name, available: availableDots }
        ));
    }
}

// Mirrors Ateliera's phomymo-print.ts rasterFor(). The only Odoo addition is
// honouring the explicit paper-side override from the settings panel.
export function phomymoRasterFor(image, deviceName, printerModel, ditherMode, align) {
    const { data: pixels, width, height } = image;
    if (isRotatedPrinter(deviceName, printerModel)) {
        const widthBytes = Math.ceil(width / 8);
        return {
            data: _pixelsToRaster(pixels, width, height, widthBytes, "left", ditherMode),
            widthBytes,
            heightLines: height,
        };
    }
    const widthBytes = getPrinterWidthBytes(deviceName, printerModel);
    const alignment = align || getPrinterAlignment(deviceName, printerModel);
    return {
        data: _pixelsToRaster(pixels, width, height, widthBytes, alignment, ditherMode),
        widthBytes,
        heightLines: height,
    };
}

async function rasterAtDpi(url, sourceDpi, targetDpi) {
    const image = await loadRaster(url);
    if (!sourceDpi || sourceDpi === targetDpi) return image;
    const ratio = targetDpi / sourceDpi;
    const source = document.createElement("canvas");
    source.width = image.width;
    source.height = image.height;
    source.getContext("2d").putImageData(image, 0, 0);
    const target = document.createElement("canvas");
    target.width = Math.max(1, Math.round(image.width * ratio));
    target.height = Math.max(1, Math.round(image.height * ratio));
    const context = target.getContext("2d", { willReadFrequently: true });
    context.fillStyle = "white";
    context.fillRect(0, 0, target.width, target.height);
    context.imageSmoothingEnabled = false;
    context.drawImage(source, 0, 0, target.width, target.height);
    return context.getImageData(0, 0, target.width, target.height);
}

function printOptions(deviceName, printerModel, settings, onProgress = () => {}) {
    return {
        isBLE: true,
        deviceName,
        printerModel,
        density: toDensity8(settings.density),
        feed: settings.feed,
        continuous: settings.continuous,
        onProgress,
    };
}

async function printImage(link, image, settings, onProgress = () => {}) {
    const deviceName = link.getDeviceName?.() || "";
    // This override is essential for M110S units advertising a Q199… serial.
    // Auto-detection in phomymo otherwise chooses a 72-byte generic head and
    // the printer feeds without burning. This is exactly Ateliera's fix.
    const device = resolveDevice(settings.model, deviceName);
    if (!reachableOverBle(device)) {
        throw new Error(_t("%(device)s requires USB and cannot use Web Bluetooth.", { device: device.name }));
    }
    assertRasterFitsDevice(image, device);
    const printerModel = device.id;
    const raster = phomymoRasterFor(
        image, deviceName, printerModel, settings.dither, settings.align
    );
    await print(link, raster, printOptions(deviceName, printerModel, settings, onProgress));
    return { device, raster };
}

function testImage(device) {
    const width = device.widthBytes === null ? 96 : device.widthBytes * 8;
    const height = 160;
    const data = new Uint8ClampedArray(width * height * 4).fill(255);
    for (let y = 0; y < height; y++) {
        if (Math.floor(y / 20) % 2) continue;
        for (let x = 8; x < width - 8; x++) {
            const offset = (y * width + x) * 4;
            data[offset] = 0;
            data[offset + 1] = 0;
            data[offset + 2] = 0;
        }
    }
    return { data, width, height };
}

export async function diagnosePhomemo(options = {}) {
    const settings = savePhomemoSettings(options);
    const started = performance.now();
    const link = await connectedTransport(Boolean(options.forceChooser));
    await link.delay(250);
    const deviceName = link.getDeviceName?.() || "";
    const device = resolveDevice(settings.model, deviceName);
    const info = link.printerInfo || {};
    return [
        `Printer: ${deviceName || "unnamed"}`,
        `Model: ${device.name} (${device.protocol})`,
        `Connection: ${Math.round(performance.now() - started)} ms`,
        `Transport: Ateliera phomymo BLE`,
        `Write mode: ${link._useWriteWithResponse ? "with response" : "without response"}`,
        `Battery: ${info.battery ?? "unknown"}`,
        `Paper: ${info.paper ?? "unknown"}`,
        `Cover: ${info.cover ?? "unknown"}`,
        `Paper position: ${settings.align || device.alignment}`,
    ].join("\n");
}

export async function testPrintPhomemo(options = {}) {
    const settings = savePhomemoSettings(options);
    const link = await connectedTransport(Boolean(options.forceChooser));
    const device = resolveDevice(settings.model, link.getDeviceName?.() || "");
    const result = await printImage(link, testImage(device), settings);
    return { bytes: result.raster.data.length, ink: 0.5 };
}

registerPrinterAdapter({
    id: "phomemo",
    label: _t("Phomemo (Ateliera transport)"),
    available: () => BLETransport.isAvailable(),
    models: phomemoModels,
    settings: loadPhomemoSettings,
    saveSettings: savePhomemoSettings,
    testConnection: diagnosePhomemo,
    testPrint: testPrintPhomemo,
    async print(job, options = {}) {
        const settings = savePhomemoSettings(options);
        const link = await connectedTransport(Boolean(options.forceChooser));
        const device = resolveDevice(settings.model, link.getDeviceName?.() || "");
        const image = await rasterAtDpi(job.png_url, Number(job.dpi), device.dpi);
        for (let copy = 0; copy < job.copies; copy++) {
            await printImage(link, image, settings);
            if (copy + 1 < job.copies) await link.delay(500);
        }
    },
});
