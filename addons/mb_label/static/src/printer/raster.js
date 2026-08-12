/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function loadRaster(url) {
    const image = new Image();
    image.crossOrigin = "same-origin";
    await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(new Error(_t("The rendered label image could not be loaded.")));
        image.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.imageSmoothingEnabled = false;
    context.drawImage(image, 0, 0);
    return context.getImageData(0, 0, canvas.width, canvas.height);
}

export function isBlack(image, x, y) {
    const offset = (y * image.width + x) * 4;
    return image.data[offset] < 160 && image.data[offset + 3] > 0;
}

export function packRows(image, widthBits = image.width, alignment = "center") {
    const widthBytes = Math.ceil(widthBits / 8);
    const sourceBytes = Math.ceil(image.width / 8);
    const left = alignment === "right" ? widthBytes - sourceBytes
        : alignment === "center" ? Math.floor((widthBytes - sourceBytes) / 2) : 0;
    const output = new Uint8Array(widthBytes * image.height);
    for (let y = 0; y < image.height; y++) {
        for (let x = 0; x < image.width; x++) {
            if (!isBlack(image, x, y)) continue;
            const target = x + Math.max(0, left * 8);
            if (target >= widthBits) continue;
            output[y * widthBytes + Math.floor(target / 8)] |= 0x80 >> (target % 8);
        }
    }
    return { data: output, widthBytes, rows: image.height };
}

export function encodeNiimbotRows(image) {
    // NIIMBOT's common D-series path prints across the narrow axis, rotating
    // the source clockwise. A 40 × 30 mm/203 dpi label becomes 240 columns
    // by 320 rows, and the column count remains byte-aligned.
    const cols = image.height;
    const rows = image.width;
    if (cols % 8) throw new Error(_t("NIIMBOT label width must resolve to a whole byte."));
    const encoded = [];
    for (let row = 0; row < rows; row++) {
        const bytes = new Uint8Array(cols / 8);
        let black = 0;
        for (let col = 0; col < cols; col++) {
            const sourceX = row;
            const sourceY = image.height - 1 - col;
            if (!isBlack(image, sourceX, sourceY)) continue;
            bytes[Math.floor(col / 8)] |= 0x80 >> (col % 8);
            black++;
        }
        encoded.push({ row, bytes, black });
    }
    return { cols, rows, encoded };
}
