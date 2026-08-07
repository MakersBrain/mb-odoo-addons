/** @odoo-module **/

import { loadRaster, packRows, sleep } from "./raster";
import { registerPrinterAdapter } from "./printer_registry";
import { selectBluetoothDevice } from "./device_memory";

export const PHOMEMO_SERVICE = "0000ff00-0000-1000-8000-00805f9b34fb";
export const PHOMEMO_WRITE = "0000ff02-0000-1000-8000-00805f9b34fb";

const bytes = (...values) => Uint8Array.from(values);

export function buildPhomemoM110Job(image, { density = 10, speed = 5, continuous = false } = {}) {
    const raster = packRows(image, 384, "center");
    return [
        bytes(0x1b, 0x4e, 0x0d, Math.max(1, Math.min(15, speed))),
        bytes(0x1b, 0x4e, 0x04, Math.max(1, Math.min(15, density))),
        bytes(0x1f, 0x11, continuous ? 0x0b : 0x0a),
        bytes(0x1d, 0x76, 0x30, 0x00, raster.widthBytes & 0xff,
            (raster.widthBytes >> 8) & 0xff, raster.rows & 0xff, (raster.rows >> 8) & 0xff),
        raster.data,
        bytes(0x1f, 0xf0, 0x05, 0x00, 0x1f, 0xf0, 0x03, 0x00),
    ];
}

async function writeChunks(characteristic, data, size = 128, pause = 18) {
    for (let offset = 0; offset < data.length; offset += size) {
        const part = data.slice(offset, offset + size);
        if (characteristic.properties.writeWithoutResponse) {
            await characteristic.writeValueWithoutResponse(part);
        } else {
            await characteristic.writeValueWithResponse(part);
        }
        await sleep(pause);
    }
}

async function connectPhomemo(forceChooser = false) {
    const device = await selectBluetoothDevice("phomemo", {
        acceptAllDevices: true,
        optionalServices: [PHOMEMO_SERVICE],
    }, { forceChooser });
    const server = await device.gatt.connect();
    const service = await server.getPrimaryService(PHOMEMO_SERVICE);
    const characteristic = await service.getCharacteristic(PHOMEMO_WRITE);
    return { device, server, characteristic };
}

registerPrinterAdapter({
    id: "phomemo",
    label: "Phomemo M110 / M120 (Bluetooth)",
    available: () => Boolean(navigator.bluetooth),
    async print(job, options = {}) {
        const image = await loadRaster(job.png_url);
        if (image.width > 384) throw new Error("This label is wider than the Phomemo M110 print head.");
        const connection = await connectPhomemo(Boolean(options.forceChooser));
        try {
            for (let copy = 0; copy < job.copies; copy++) {
                const packets = buildPhomemoM110Job(image, options);
                for (const packet of packets) {
                    await writeChunks(connection.characteristic, packet);
                    await sleep(packet === packets[4] ? 250 : 35);
                }
                await sleep(500);
            }
        } finally {
            connection.server.disconnect();
        }
    },
});
