import { expect, test } from "@odoo/hoot";
import { buildPhomemoM110Job } from "@mb_label/printer/phomemo_adapter";
import { buildNiimbotD110Job, niimbotPacket } from "@mb_label/printer/niimbot_adapter";
import { exportLegacyTemplate, importLegacyTemplate } from "@mb_label/editor/legacy_template";
import { shouldClearWorkspaceSelection } from "@mb_label/editor/selection";
import {
    applyPrinterProfile, matchingMediaId, printerProfile, printerProfileId,
} from "@mb_label/editor/printer_presets";
import { formatTemplateText } from "@mb_label/editor/template_formatters";
import {
    rememberAdapter, rememberedAdapter, selectBluetoothDevice,
} from "@mb_label/printer/device_memory";

function whiteImage(width, height) {
    return { width, height, data: new Uint8ClampedArray(width * height * 4).fill(255) };
}

function blackPixel(image, x, y) {
    const offset = (y * image.width + x) * 4;
    image.data[offset] = 0;
    image.data[offset + 1] = 0;
    image.data[offset + 2] = 0;
}

function memoryStorage() {
    const values = new Map();
    return {
        getItem: (key) => values.get(key) || null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
    };
}

test("printer destination and granted BLE device are reused until another is requested", async () => {
    const storage = memoryStorage();
    const first = { id: "printer-a", name: "Workshop printer" };
    const second = { id: "printer-b", name: "Packing printer" };
    let chooserCalls = 0;
    const bluetooth = {
        getDevices: async () => [first],
        requestDevice: async () => {
            chooserCalls++;
            return chooserCalls === 1 ? first : second;
        },
    };
    rememberAdapter("phomemo", storage);
    expect(rememberedAdapter(storage)).toBe("phomemo");
    expect(await selectBluetoothDevice("phomemo", {}, { bluetooth, storage })).toBe(first);
    expect(chooserCalls).toBe(1);
    expect(await selectBluetoothDevice("phomemo", {}, { bluetooth, storage })).toBe(first);
    expect(chooserCalls).toBe(1);
    expect(await selectBluetoothDevice(
        "phomemo", {}, { bluetooth, storage, forceChooser: true })).toBe(second);
    expect(chooserCalls).toBe(2);
});

test("releasing a selected label element does not clear the selection", () => {
    const element = { closest: (selector) => selector === ".o_mb_label_element" ? element : null };
    const child = { closest: (selector) => selector === ".o_mb_label_element" ? element : null };
    const workspace = { closest: () => null };
    expect(shouldClearWorkspaceSelection({ target: element })).toBe(false);
    expect(shouldClearWorkspaceSelection({ target: child })).toBe(false);
    expect(shouldClearWorkspaceSelection({ target: workspace })).toBe(true);
    expect(shouldClearWorkspaceSelection()).toBe(true);
});

test("printer selection applies resolution and matching media defaults", () => {
    const source = { width_mm: 62, height_mm: 100, dpi: 300, continuous_media: true };
    const phomemo = applyPrinterProfile(source, "phomemo");
    expect(phomemo).toMatchObject({
        printer_target: "phomemo", dpi: 203, width_mm: 40, height_mm: 30,
        round_media: false, continuous_media: false,
    });
    const niimbot = applyPrinterProfile(source, "niimbot");
    expect(niimbot).toMatchObject({
        printer_target: "niimbot", dpi: 203, width_mm: 40, height_mm: 15,
    });
    expect(matchingMediaId(niimbot, printerProfile("niimbot"))).toBe("40x15");
    expect(printerProfileId("m110")).toBe("phomemo");
    expect(printerProfileId("D110")).toBe("niimbot");
});

test("template filters format money, decimals, defaults, and text in the preview", () => {
    const values = {
        "product.price": "45.00 EUR", "product.price.raw": 45.5,
        "product.name": "  blue CUP  ", "company.currency": "EUR",
    };
    const trimmedMoney = formatTemplateText("{{product.price|money_trim}}", values);
    expect(trimmedMoney).toMatch(/45/);
    expect(trimmedMoney.includes(".00") || trimmedMoney.includes(",00")).toBe(false);
    expect(formatTemplateText("{{product.price.raw|fixed:1}}", values)).toMatch(/45[.,]5/);
    expect(formatTemplateText("{{product.name|trim|title}}", values)).toBe("Blue Cup");
    expect(formatTemplateText("{{manual.note|default:No note}}", values)).toBe("No note");
    expect(formatTemplateText("{{manual.note|default:No note}}", { ...values, "manual.note": "" })).toBe("No note");
});

test("Phomemo M110 job declares a 48-byte head and contains raster data", () => {
    const image = whiteImage(8, 2);
    blackPixel(image, 0, 0);
    const packets = buildPhomemoM110Job(image, { density: 12, speed: 4 });
    expect([...packets[0]]).toEqual([0x1b, 0x4e, 0x0d, 4]);
    expect([...packets[1]]).toEqual([0x1b, 0x4e, 0x04, 12]);
    expect([...packets[3].slice(0, 6)]).toEqual([0x1d, 0x76, 0x30, 0, 48, 0]);
    expect(packets[4].length).toBe(96);
    expect(packets[4].some((value) => value !== 0)).toBe(true);
});

test("NIIMBOT packets use guarded framing and XOR checksum", () => {
    const packet = niimbotPacket(0x21, [2]);
    expect([...packet]).toEqual([0x55, 0x55, 0x21, 1, 2, 0x22, 0xaa, 0xaa]);
    const connect = niimbotPacket(0xc1, [1], true);
    expect(connect[0]).toBe(3);
    expect([...connect.slice(1, 3)]).toEqual([0x55, 0x55]);
});

test("NIIMBOT D110 job contains page geometry, every row, and print end", () => {
    const image = whiteImage(2, 8);
    blackPixel(image, 0, 0);
    const packets = buildNiimbotD110Job(image);
    expect(packets[0][0]).toBe(3);
    expect(packets.some((packet) => packet[2] === 0x13)).toBe(true);
    expect(packets.filter((packet) => packet[2] === 0x84 || packet[2] === 0x85).length).toBe(2);
    expect(packets.at(-2)[2]).toBe(0xe3);
    expect(packets.at(-1)[2]).toBe(0xf3);
});

test("old version-3 JSON converts printer dots, fields, styles, groups, and media", () => {
    const imported = importLegacyTemplate({
        name: "Old cup", version: 3, dotsPerMm: 8, target: "m110",
        labelSize: { width: 40, height: 30, round: true },
        fields: [
            { key: "name", source: "auto", binding: "core.product.title" },
            { key: "note", source: "manual" },
        ],
        elements: [
            {
                id: "title", type: "text", x: 8, y: 16, width: 160, height: 32,
                text: "{{name}} – {{note}}", fontSize: 16, fontFamily: "Georgia, serif",
                fontStyle: "italic", textDecoration: "underline", groupId: "g1", required: false,
            },
            {
                id: "shape", type: "shape", shapeType: "ellipse", x: 0, y: 0,
                width: 80, height: 80, fill: "dither-medium",
            },
        ],
    }, "fallback");
    expect(imported.name).toBe("Old cup");
    expect(imported.settings.width_mm).toBe(40);
    expect(imported.settings.dpi).toBe(203);
    expect(imported.settings.round_media).toBe(true);
    expect(imported.document.elements[0]).toMatchObject({
        x: 1, y: 2, width: 20, height: 4,
        text: "{{product.name}} – {{manual.note}}", font_size: 2,
        font: "serif", italic: true, underline: true, group_id: "g1", required: false,
    });
    expect(imported.document.elements[1]).toMatchObject({
        type: "ellipse", width: 10, height: 10, filled: true, tint: "50",
    });
});

test("Odoo label JSON exports as version 3 and round-trips physical geometry", () => {
    const template = {
        name: "Cup", width_mm: 40, height_mm: 30, dpi: 203,
        printer_target: "system", round_media: false, continuous_media: true,
    };
    const document = { schema: 1, elements: [{
        id: "qr", type: "qr", x: 2, y: 3, width: 12, height: 12,
        data: "{{qr}}", rotation: 15, quiet_zone: 2,
    }] };
    const exported = exportLegacyTemplate(template, document);
    expect(exported).toMatchObject({ version: 3, widthMm: 40, heightMm: 30, continuous: true });
    const back = importLegacyTemplate(exported, "Cup");
    expect(Math.abs(back.document.elements[0].x - 2)).toBeLessThan(0.0001);
    expect(Math.abs(back.document.elements[0].width - 12)).toBeLessThan(0.0001);
    expect(back.document.elements[0].data).toBe("{{qr}}");
    expect(back.document.elements[0].quiet_zone).toBe(2);
});

test("optional element state survives old JSON export and import", () => {
    const template = { name: "Optional lot", width_mm: 40, height_mm: 30, dpi: 203 };
    const document = { schema: 1, elements: [{
        id: "lot", type: "text", x: 1, y: 1, width: 20, height: 5,
        text: "{{lot.name}}", required: false,
    }] };
    const exported = exportLegacyTemplate(template, document);
    expect(exported.elements[0].required).toBe(false);
    expect(importLegacyTemplate(exported).document.elements[0].required).toBe(false);
});
