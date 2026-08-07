/** @odoo-module **/

// Packet framing and the common D110 print sequence follow the MIT-licensed
// niimbluelib protocol documentation. The transport remains isolated here so
// another NIIMBOT firmware family can be added without touching Label Studio.
import { encodeNiimbotRows, loadRaster, sleep } from "./raster";
import { registerPrinterAdapter } from "./printer_registry";
import { selectBluetoothDevice } from "./device_memory";

export const NIIMBOT_SERVICE = "e7810a71-73ae-499d-8c15-faa9aef0c3f2";

const u16 = (value) => [(value >> 8) & 0xff, value & 0xff];

export function niimbotPacket(command, data = [1], connect = false) {
    const payload = Uint8Array.from(data);
    let checksum = command ^ payload.length;
    for (const value of payload) checksum ^= value;
    const packet = Uint8Array.from([0x55, 0x55, command, payload.length, ...payload, checksum, 0xaa, 0xaa]);
    return connect ? Uint8Array.from([0x03, ...packet]) : packet;
}

function pixelCounts(data, printheadPixels) {
    const chunk = Math.floor(printheadPixels / 8 / 3);
    const parts = [0, 0, 0];
    let total = 0;
    for (let index = 0; index < data.length; index++) {
        for (let bit = 0; bit < 8; bit++) {
            if (!(data[index] & (1 << bit))) continue;
            total++;
            if (index < chunk * 3) parts[Math.floor(index / chunk)]++;
        }
    }
    if (data.length <= chunk * 3 && parts.every((value) => value <= 255)) return parts;
    return [0, total & 0xff, (total >> 8) & 0xff];
}

export function buildNiimbotD110Job(image, { density = 2, labelType = 1 } = {}) {
    const encoded = encodeNiimbotRows(image);
    const packets = [
        niimbotPacket(0xc1, [1], true),
        niimbotPacket(0x21, [Math.max(1, Math.min(5, density))]),
        niimbotPacket(0x23, [labelType]),
        niimbotPacket(0x01, [1]),
        niimbotPacket(0x20, [1]),
        niimbotPacket(0x03, [1]),
        niimbotPacket(0x13, [...u16(encoded.rows), ...u16(encoded.cols)]),
        niimbotPacket(0x15, [0, 1]),
    ];
    for (const row of encoded.encoded) {
        if (!row.black) {
            packets.push(niimbotPacket(0x84, [...u16(row.row), 1]));
        } else {
            packets.push(niimbotPacket(0x85, [
                ...u16(row.row), ...pixelCounts(row.bytes, encoded.cols), 1, ...row.bytes,
            ]));
        }
    }
    packets.push(niimbotPacket(0xe3, [1]), niimbotPacket(0xf3, [1]));
    return packets;
}

async function connectNiimbot(forceChooser = false) {
    const device = await selectBluetoothDevice("niimbot", {
        filters: [{ services: [NIIMBOT_SERVICE] }],
        optionalServices: [NIIMBOT_SERVICE],
    }, { forceChooser });
    const server = await device.gatt.connect();
    const services = await server.getPrimaryServices();
    for (const service of services) {
        const characteristics = await service.getCharacteristics();
        const channel = characteristics.find((item) => item.properties.writeWithoutResponse);
        if (!channel) continue;
        const notify = characteristics.find((item) => item.properties.notify);
        if (notify) await notify.startNotifications();
        return { device, server, channel };
    }
    server.disconnect();
    throw new Error("No writable NIIMBOT Bluetooth channel was found.");
}

registerPrinterAdapter({
    id: "niimbot",
    label: "NIIMBOT D110 family (Bluetooth)",
    available: () => Boolean(navigator.bluetooth),
    async print(job, options = {}) {
        const image = await loadRaster(job.png_url);
        const connection = await connectNiimbot(Boolean(options.forceChooser));
        try {
            for (let copy = 0; copy < job.copies; copy++) {
                for (const packet of buildNiimbotD110Job(image, options)) {
                    await connection.channel.writeValueWithoutResponse(packet);
                    await sleep(packet[2] === 0x85 ? 8 : 55);
                }
                await sleep(700);
            }
        } finally {
            connection.server.disconnect();
        }
    },
});
