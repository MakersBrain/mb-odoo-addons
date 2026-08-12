/* Makersbrain inventory capture worker. No network access and no frame retention. */
const FORMATS = ["ean_8", "ean_13", "upc_a", "upc_e", "code_128", "qr_code", "data_matrix"];
let detector;

function quality(bitmap) {
    const width = Math.min(bitmap.width, 640);
    const height = Math.max(1, Math.round(bitmap.height * width / bitmap.width));
    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext("2d", {willReadFrequently: true});
    context.drawImage(bitmap, 0, 0, width, height);
    const pixels = context.getImageData(0, 0, width, height).data;
    let total = 0;
    let clipped = 0;
    let edges = 0;
    let previous = 0;
    for (let offset = 0; offset < pixels.length; offset += 4) {
        const luminance = (77 * pixels[offset] + 150 * pixels[offset + 1] + 29 * pixels[offset + 2]) >> 8;
        total += luminance;
        clipped += luminance < 12 || luminance > 245 ? 1 : 0;
        if (offset >= 4) {
            edges += Math.abs(luminance - previous);
        }
        previous = luminance;
    }
    const count = pixels.length / 4;
    const mean = total / count;
    const edgeMean = edges / Math.max(1, count - 1);
    // A code, not a sentence: this worker is loaded by URL rather than bundled,
    // so it cannot import _t. The client action turns the code into the
    // translated hint the user reads.
    let hintCode = "steady";
    if (mean < 45) {
        hintCode = "dark";
    } else if (mean > 225 || clipped / count > 0.3) {
        hintCode = "glare";
    } else if (edgeMean < 5) {
        hintCode = "closer";
    } else {
        hintCode = "ready";
    }
    return {mean, edgeMean, clippedRatio: clipped / count, hintCode};
}

self.onmessage = async ({data}) => {
    if (data.type !== "frame" || !data.bitmap) {
        return;
    }
    const bitmap = data.bitmap;
    try {
        const frameQuality = quality(bitmap);
        let codes = [];
        if ("BarcodeDetector" in self) {
            if (!detector) {
                const supported = await BarcodeDetector.getSupportedFormats();
                const formats = FORMATS.filter((format) => supported.includes(format));
                detector = formats.length ? new BarcodeDetector({formats}) : false;
            }
            if (detector) {
                codes = (await detector.detect(bitmap)).map(({rawValue, format}) => ({rawValue, format}));
            }
        }
        self.postMessage({type: "result", generation: data.generation, quality: frameQuality, codes});
    } catch (error) {
        self.postMessage({type: "error", generation: data.generation, message: error.message});
    } finally {
        bitmap.close();
    }
};
