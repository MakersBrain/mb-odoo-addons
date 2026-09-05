import { expect, test } from "@odoo/hoot";
import { mockFetch } from "@odoo/hoot-mock";
import {
    assertRasterFitsDevice, phomymoRasterFor,
} from "@mb_label/printer/phomemo_adapter";
import { BLETransport } from "@mb_label/printer/phomymo/ble";
import {
    printerProtocolDebug, setPrinterProtocolDebug,
} from "@mb_label/printer/phomymo/debug";
import {
    loadPrinterDefinitions, print as printPhomymo,
} from "@mb_label/printer/phomymo/printer";
import {
    allDevices, detectDevice, resolveDevice,
} from "@mb_label/printer/mb_phomemo/devices";
import { buildNiimbotD110Job, niimbotPacket } from "@mb_label/printer/niimbot_adapter";
import { shouldClearWorkspaceSelection } from "@mb_label/editor/selection";
import { parseTemplateFile, serializeTemplateFile } from "@mb_label/editor/template_file";
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

test("printer protocol diagnostics are opt-in and redact identifiers and bytes", () => {
    const calls = [];
    const originalDebug = console.debug;
    console.debug = (...args) => calls.push(args);
    try {
        printerProtocolDebug("Device Workshop-M110 bytes ff00", {
            device: "Workshop-M110",
            bytes: [0xff, 0x00],
            attempt: 2,
        });
        expect(calls.length).toBe(0);

        setPrinterProtocolDebug(true);
        printerProtocolDebug("Device Workshop-M110 bytes ff00", {
            device: "Workshop-M110",
            bytes: [0xff, 0x00],
            attempt: 2,
        });
        expect(calls.length).toBe(1);
        expect(calls[0][0]).toBe("[Phomymo] protocol-event");
        expect(calls[0][1]).toEqual({ attempt: 2 });
        expect(JSON.stringify(calls[0])).not.toMatch(/Workshop-M110|ff00|255/);
    } finally {
        setPrinterProtocolDebug(false);
        console.debug = originalDebug;
    }
});

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

test("MakersBrain phomymo sends the working M110 command stream", async () => {
    mockFetch((route) => {
        expect(route).toBe("/mb_label/static/src/printer/phomymo/printers.json");
        return {
            printers: [{
                id: "m110",
                name: "M110 / M120",
                protocol: "m110",
                widthBytes: 48,
                dpi: 203,
                alignment: "center",
                rotated: false,
                namePatterns: ["M110", "M120"],
                builtin: true,
            }],
        };
    });
    await loadPrinterDefinitions();
    const image = whiteImage(8, 2);
    blackPixel(image, 0, 0);
    const raster = phomymoRasterFor(image, "M110", "m110", "threshold");
    const writes = [];
    const transport = {
        send: async (bytes) => writes.push([...bytes]),
        delay: async () => {},
    };
    await printPhomymo(transport, raster, {
        isBLE: true, deviceName: "M110", printerModel: "m110",
        density: 6, feed: 32, continuous: false,
    });
    expect(writes[0]).toEqual([0x1b, 0x4e, 0x0d, 5]);
    expect(writes[1].slice(0, 3)).toEqual([0x1b, 0x4e, 0x04]);
    expect(writes[2]).toEqual([0x1f, 0x11, 0x0a]);
    expect(writes[3]).toEqual([0x1d, 0x76, 0x30, 0, 48, 0, 2, 0]);
    expect(writes.at(-1)).toEqual([0x1f, 0xf0, 0x05, 0, 0x1f, 0xf0, 0x03, 0]);
    expect(writes.slice(4, -1).flat().length).toBe(96);
});

test("MakersBrain Phomemo definitions cover every supported protocol family", () => {
    const devices = allDevices();
    expect(devices.length).toBe(18);
    const actualProtocols = [...new Set(devices.map((device) => device.protocol))].sort();
    const supportedProtocols = [
        "m-series", "m02", "m04", "m110", "d-series", "p12", "tspl",
    ].sort();
    expect(actualProtocols).toEqual(supportedProtocols);
    expect(detectDevice("M110").id).toBe("m110");
    expect(detectDevice("D110").id).toBe("d-series");
    expect(resolveDevice("auto", "Q199G4130440005").id).toBe("m110");
});

test("MakersBrain transport falls back to acknowledged writes on this M110 link", async () => {
    const acknowledged = [];
    const transport = {
        isConnected: () => true,
        _useWriteWithResponse: false,
        writeChar: {
            writeValueWithoutResponse: async () => {
                throw new Error("write without response rejected");
            },
            writeValue: async (buffer) => acknowledged.push([...new Uint8Array(buffer)]),
        },
    };
    const source = Uint8Array.from([9, 1, 2, 3, 9]);
    await BLETransport.prototype.send.call(transport, source.subarray(1, 4));
    expect(transport._useWriteWithResponse).toBe(true);
    expect(acknowledged).toEqual([[1, 2, 3]]);
});

test("Phomemo rejects paper wider than the selected head instead of cropping it", () => {
    expect(() => assertRasterFitsDevice(whiteImage(385, 20), resolveDevice("m110"))).toThrow();
    expect(() => assertRasterFitsDevice(whiteImage(384, 20), resolveDevice("m110"))).not.toThrow();
    expect(() => assertRasterFitsDevice(whiteImage(160, 97), resolveDevice("p12"))).toThrow();
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

test("current label template files round-trip physical geometry and settings", () => {
    const template = {
        name: "Cup", width_mm: 40, height_mm: 30, dpi: 203,
        printer_target: "system", round_media: false, continuous_media: true,
    };
    const document = { schema: 1, elements: [{
        id: "qr", type: "qr", x: 2, y: 3, width: 12, height: 12,
        data: "{{qr}}", rotation: 15, quiet_zone: 2,
    }] };
    const exported = serializeTemplateFile(template, document);
    expect(exported).toMatchObject({
        schema: 1,
        settings: { width_mm: 40, height_mm: 30, dpi: 203, continuous_media: true },
    });
    const back = parseTemplateFile(exported, "Cup");
    expect(Math.abs(back.document.elements[0].x - 2)).toBeLessThan(0.0001);
    expect(Math.abs(back.document.elements[0].width - 12)).toBeLessThan(0.0001);
    expect(back.document.elements[0].data).toBe("{{qr}}");
    expect(back.document.elements[0].quiet_zone).toBe(2);
});

test("optional element state survives current JSON export and import", () => {
    const template = { name: "Optional lot", width_mm: 40, height_mm: 30, dpi: 203 };
    const document = { schema: 1, elements: [{
        id: "lot", type: "text", x: 1, y: 1, width: 20, height: 5,
        text: "{{lot.name}}", required: false,
    }] };
    const exported = serializeTemplateFile(template, document);
    expect(exported.document.elements[0].required).toBe(false);
    expect(parseTemplateFile(exported).document.elements[0].required).toBe(false);
});
