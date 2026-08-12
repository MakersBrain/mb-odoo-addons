/** @odoo-module **/
/* global ZXing */

import { Component, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const BARCODE_FORMATS = [
    "ean_8", "ean_13", "upc_a", "upc_e", "code_128", "qr_code", "data_matrix",
];
const FRAME_INTERVAL_MS = 250;
// The frame worker is loaded by URL and cannot import _t, so it reports a
// quality code and the translated sentence is chosen here.
const FRAME_QUALITY_HINTS = {
    steady: () => _t("Hold steady and fill the frame with the label."),
    dark: () => _t("More light is needed."),
    glare: () => _t("Reduce glare or tilt the package."),
    closer: () => _t("Move closer and hold steady."),
    ready: () => _t("Ready - keep the barcode inside the guide."),
};
const CONSENSUS_WINDOW_MS = 1800;

export function gtinCheckDigitIsValid(value, format = "") {
    const digits = String(value || "").replace(/\D/g, "");
    if (format && !["ean_8", "ean_13", "upc_a", "upc_e"].includes(format)) {
        // QR, Data Matrix and Code 128 may carry a complete GS1 element string;
        // applying a check digit to all of its concatenated digits is invalid.
        return true;
    }
    if (format === "upc_e" && digits.length === 8) {
        const numberSystem = digits[0];
        const payload = digits.slice(1, 7);
        const check = digits[7];
        if (!["0", "1"].includes(numberSystem)) {
            return false;
        }
        const last = payload[5];
        let body;
        if ("012".includes(last)) {
            body = numberSystem + payload.slice(0, 2) + last + "0000" + payload.slice(2, 5);
        } else if (last === "3") {
            body = numberSystem + payload.slice(0, 3) + "00000" + payload.slice(3, 5);
        } else if (last === "4") {
            body = numberSystem + payload.slice(0, 4) + "00000" + payload[4];
        } else {
            body = numberSystem + payload.slice(0, 5) + "0000" + last;
        }
        return gtinCheckDigitIsValid(body + check, "upc_a");
    }
    if (![8, 12, 13, 14].includes(digits.length)) {
        return true;
    }
    const expected = Number(digits.at(-1));
    const body = digits.slice(0, -1);
    let sum = 0;
    for (let index = body.length - 1, weight = 3; index >= 0; index -= 1, weight = weight === 3 ? 1 : 3) {
        sum += Number(body[index]) * weight;
    }
    return (10 - (sum % 10)) % 10 === expected;
}

export function consensusCandidate(observations, now, windowMs = CONSENSUS_WINDOW_MS) {
    const recent = observations.filter((item) => now - item.at <= windowMs);
    for (let index = recent.length - 1; index >= 0; index -= 1) {
        const candidate = recent[index];
        if (!gtinCheckDigitIsValid(candidate.rawValue, candidate.format)) {
            continue;
        }
        if (recent.some((item, otherIndex) => otherIndex !== index
            && item.rawValue === candidate.rawValue && item.format === candidate.format)) {
            return candidate;
        }
    }
    return null;
}

export function bytesToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunk = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunk) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
    }
    return btoa(binary);
}

async function detectWithOdooZXing(file) {
    await loadJS("/web/static/lib/zxing-library/zxing-library.js");
    const bitmap = await createImageBitmap(file);
    try {
        const canvas = document.createElement("canvas");
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        canvas.getContext("2d").drawImage(bitmap, 0, 0);
        const formats = [
            ZXing.BarcodeFormat.EAN_8,
            ZXing.BarcodeFormat.EAN_13,
            ZXing.BarcodeFormat.UPC_A,
            ZXing.BarcodeFormat.UPC_E,
            ZXing.BarcodeFormat.CODE_128,
            ZXing.BarcodeFormat.QR_CODE,
            ZXing.BarcodeFormat.DATA_MATRIX,
        ];
        const reader = new ZXing.MultiFormatReader();
        reader.setHints(new Map([
            [ZXing.DecodeHintType.POSSIBLE_FORMATS, formats],
            [ZXing.DecodeHintType.TRY_HARDER, true],
        ]));
        const source = new ZXing.HTMLCanvasElementLuminanceSource(canvas);
        const binary = new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(source));
        const formatNames = new Map([
            [ZXing.BarcodeFormat.EAN_8, "ean_8"],
            [ZXing.BarcodeFormat.EAN_13, "ean_13"],
            [ZXing.BarcodeFormat.UPC_A, "upc_a"],
            [ZXing.BarcodeFormat.UPC_E, "upc_e"],
            [ZXing.BarcodeFormat.CODE_128, "code_128"],
            [ZXing.BarcodeFormat.QR_CODE, "qr_code"],
            [ZXing.BarcodeFormat.DATA_MATRIX, "data_matrix"],
        ]);
        let results = [];
        if (ZXing.GenericMultipleBarcodeReader) {
            try {
                results = new ZXing.GenericMultipleBarcodeReader(reader).decodeMultiple(binary) || [];
            } catch (error) {
                if (error.name !== "NotFoundException") {
                    throw error;
                }
            }
        }
        if (!results.length) {
            results = [reader.decode(binary)];
        }
        return results.map((result) => ({
            rawValue: result.getText(),
            format: formatNames.get(result.getBarcodeFormat()) || "unknown",
        }));
    } catch (error) {
        if (error.name === "NotFoundException") {
            return [];
        }
        throw error;
    } finally {
        bitmap.close();
    }
}

export class InventoryCaptureAction extends Component {
    static template = "mb_inventory_capture.CaptureAction";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.video = useRef("video");
        this.fileInput = useRef("fileInput");
        this.stream = null;
        this.worker = null;
        this.frameTimer = null;
        this.frameBusy = false;
        this.observations = [];
        this.scanGeneration = 0;
        this.stableCode = null;
        this.previewUrl = null;
        this.state = useState({
            captureId: null,
            captureName: "",
            cameraActive: false,
            busy: false,
            role: "front",
            previewUrl: null,
            decoded: [],
            uploaded: false,
            manualCode: "",
            scanHint: _t("Start the camera to scan a barcode."),
            lookupState: "idle",
            productFound: false,
            torchAvailable: false,
            torchOn: false,
            lastAssetId: null,
            cropReady: false,
            cropRotation: 0,
            cropRect: [0.08, 0.22, 0.92, 0.82],
            enhanceCrop: false,
            uploadedRoles: [],
        });
        onWillUnmount(() => this.cleanup());
    }

    cleanup() {
        this.stopLiveScan();
        if (this.stream) {
            for (const track of this.stream.getTracks()) {
                track.stop();
            }
            this.stream = null;
        }
        if (this.previewUrl) {
            URL.revokeObjectURL(this.previewUrl);
            this.previewUrl = null;
        }
    }

    stopLiveScan() {
        if (this.frameTimer) {
            clearTimeout(this.frameTimer);
            this.frameTimer = null;
        }
        if (this.worker) {
            this.worker.terminate();
            this.worker = null;
        }
        this.frameBusy = false;
    }

    async ensureCapture() {
        if (this.state.captureId) {
            return this.state.captureId;
        }
        const pickingId = this.props.action.context?.default_picking_id;
        const result = pickingId
            ? await this.orm.call("mb.inventory.capture", "create_for_receipt", [pickingId])
            : (await this.orm.create("mb.inventory.capture", [{}]))[0];
        this.state.captureId = typeof result === "object" ? result.id : result;
        this.state.captureName = typeof result === "object" ? result.name : _t("New capture");
        return this.state.captureId;
    }

    async startCamera() {
        if (!navigator.mediaDevices?.getUserMedia) {
            this.notification.add(_t("This browser has no camera API; use file upload."), {
                type: "warning",
            });
            return;
        }
        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: { ideal: "environment" },
                    width: {ideal: 1280},
                    focusMode: {ideal: "continuous"},
                },
                audio: false,
            });
            this.video.el.srcObject = this.stream;
            await this.video.el.play();
            this.state.cameraActive = true;
            const track = this.stream.getVideoTracks()[0];
            this.state.torchAvailable = Boolean(track?.getCapabilities?.().torch);
            this.startLiveScan();
        } catch {
            this.notification.add(_t("Camera permission was denied; use file upload."), {
                type: "warning",
            });
        }
    }

    startLiveScan() {
        this.stopLiveScan();
        this.scanGeneration += 1;
        this.observations = [];
        this.stableCode = null;
        this.state.lookupState = "scanning";
        this.state.scanHint = _t("Keep the barcode inside the guide.");
        if (window.Worker && window.OffscreenCanvas && window.createImageBitmap) {
            this.worker = new Worker("/mb_inventory_capture/static/lib/capture_worker.js");
            this.worker.onmessage = (event) => this.onWorkerResult(event.data);
            this.scheduleFrame(0);
        } else {
            this.state.scanHint = _t("Live scanning is unavailable; take a photo to decode it.");
        }
    }

    scheduleFrame(delay = FRAME_INTERVAL_MS) {
        if (!this.worker || !this.state.cameraActive || this.stableCode) {
            return;
        }
        this.frameTimer = setTimeout(() => this.sampleFrame(), delay);
    }

    async sampleFrame() {
        const video = this.video.el;
        if (!video?.videoWidth || this.frameBusy || !this.worker) {
            this.scheduleFrame();
            return;
        }
        this.frameBusy = true;
        try {
            const bitmap = await createImageBitmap(video);
            this.worker.postMessage({type: "frame", generation: this.scanGeneration, bitmap}, [bitmap]);
        } catch {
            this.frameBusy = false;
            this.scheduleFrame(500);
        }
    }

    async onWorkerResult(result) {
        this.frameBusy = false;
        if (result.generation !== this.scanGeneration || this.stableCode) {
            return;
        }
        const hint = FRAME_QUALITY_HINTS[result.quality?.hintCode];
        if (hint) {
            this.state.scanHint = hint();
        }
        const now = Date.now();
        this.observations = this.observations.filter((item) => now - item.at <= CONSENSUS_WINDOW_MS);
        for (const code of result.codes || []) {
            this.observations.push({...code, at: now});
        }
        const stable = consensusCandidate(this.observations, now);
        if (stable) {
            this.stableCode = stable;
            navigator.vibrate?.(50);
            await this.resolveStableCode(stable, this.scanGeneration);
            return;
        }
        this.scheduleFrame();
    }

    scanAgain() {
        this.state.decoded = [];
        this.state.productFound = false;
        this.startLiveScan();
    }

    async resolveStableCode(code, generation) {
        this.state.scanHint = _t("Barcode read. Looking up product…");
        this.state.lookupState = "local";
        const captureId = await this.ensureCapture();
        try {
            const result = await this.orm.call("mb.inventory.capture", "action_record_scan", [
                [captureId], code.rawValue, code.format,
            ]);
            if (generation !== this.scanGeneration) {
                return;
            }
            this.state.decoded = [{rawValue: code.rawValue, format: code.format}];
            this.state.productFound = Boolean(result.product_ids?.length);
            this.state.lookupState = this.state.productFound ? "found" : "not_found";
            this.state.scanHint = this.state.productFound
                ? result.lot_guidance
                : _t("Barcode saved. Checking the shared product cache…");
            if (!this.state.productFound && result.gtin) {
                this.state.lookupState = "online";
                try {
                    const online = await this.orm.call(
                        "mb.inventory.capture", "action_external_barcode_lookup",
                        [[captureId], result.gtin],
                    );
                    if (generation !== this.scanGeneration) {
                        return;
                    }
                    this.state.lookupState = online.candidate_count ? "candidate" : "not_found";
                    this.state.scanHint = online.candidate_count
                        ? online.lot_guidance
                        : _t("No online product match. Continue with the lot photo or enter the product manually.");
                } catch {
                    if (generation === this.scanGeneration) {
                        this.state.lookupState = "deferred";
                        this.state.scanHint = _t("Online lookup is unavailable. Barcode saved; continue with the lot photo.");
                    }
                }
            }
        } catch (error) {
            if (generation === this.scanGeneration) {
                this.state.lookupState = "error";
                this.state.scanHint = error.data?.message || _t("Product lookup failed; you can keep capturing.");
            }
        }
    }

    async toggleTorch() {
        const track = this.stream?.getVideoTracks?.()[0];
        if (!track || !this.state.torchAvailable) {
            return;
        }
        const next = !this.state.torchOn;
        try {
            await track.applyConstraints({advanced: [{torch: next}]});
            this.state.torchOn = next;
        } catch {
            this.state.torchAvailable = false;
        }
    }

    async takePhoto() {
        const video = this.video.el;
        if (!video?.videoWidth) {
            return;
        }
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext("2d").drawImage(video, 0, 0);
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
        await this.processFile(new File([blob], "camera.jpg", { type: "image/jpeg" }));
    }

    async onFileChange(event) {
        const file = event.target.files?.[0];
        if (file) {
            await this.processFile(file);
        }
        event.target.value = "";
    }

    async processFile(file) {
        this.state.busy = true;
        try {
            const captureId = await this.ensureCapture();
            const buffer = await file.arrayBuffer();
            const asset = await this.orm.call("mb.inventory.capture", "upload_image", [
                [captureId], bytesToBase64(buffer), this.state.role, file.name,
            ]);
            this.state.lastAssetId = asset.id;
            this.state.cropReady = false;
            this.state.cropRect = [0.08, 0.22, 0.92, 0.82];
            if (this.previewUrl) {
                URL.revokeObjectURL(this.previewUrl);
            }
            this.previewUrl = URL.createObjectURL(file);
            this.state.previewUrl = this.previewUrl;
            this.state.uploaded = true;
            if (!this.state.uploadedRoles.includes(this.state.role)) {
                this.state.uploadedRoles.push(this.state.role);
            }
            await this.detectCodes(file);
        } catch (error) {
            this.notification.add(error.data?.message || error.message || _t("Upload failed."), {
                type: "danger",
            });
        } finally {
            this.state.busy = false;
        }
    }

    async createLotCrop() {
        if (!this.state.captureId || !this.state.lastAssetId) {
            return;
        }
        this.state.busy = true;
        try {
            await this.orm.call("mb.inventory.capture", "create_lot_crop", [
                [this.state.captureId], this.state.lastAssetId,
                this.state.cropRect, Number(this.state.cropRotation), this.state.enhanceCrop,
            ]);
            this.state.cropReady = true;
            this.notification.add(_t("The selected lot area will be analyzed first."), {
                type: "success",
            });
        } catch (error) {
            this.notification.add(error.data?.message || error.message || _t("The crop could not be created."), {
                type: "danger",
            });
        } finally {
            this.state.busy = false;
        }
    }

    cropPoint(event) {
        const bounds = event.currentTarget.getBoundingClientRect();
        return [
            Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
            Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
        ];
    }

    onCropPointerDown(event) {
        event.preventDefault();
        event.currentTarget.setPointerCapture?.(event.pointerId);
        this.cropStart = this.cropPoint(event);
        this.state.cropRect = [
            this.cropStart[0], this.cropStart[1],
            Math.min(1, this.cropStart[0] + 0.01), Math.min(1, this.cropStart[1] + 0.01),
        ];
        this.state.cropReady = false;
    }

    onCropPointerMove(event) {
        if (!this.cropStart) {
            return;
        }
        event.preventDefault();
        const point = this.cropPoint(event);
        this.state.cropRect = [
            Math.min(this.cropStart[0], point[0]), Math.min(this.cropStart[1], point[1]),
            Math.max(this.cropStart[0], point[0]), Math.max(this.cropStart[1], point[1]),
        ];
    }

    onCropPointerUp(event) {
        if (!this.cropStart) {
            return;
        }
        this.onCropPointerMove(event);
        this.cropStart = null;
        const [left, top, right, bottom] = this.state.cropRect;
        if (right - left < 0.05 || bottom - top < 0.05) {
            this.state.cropRect = [0.08, 0.22, 0.92, 0.82];
        }
    }

    get cropStyle() {
        const [left, top, right, bottom] = this.state.cropRect;
        return `left:${left * 100}%;top:${top * 100}%;width:${(right - left) * 100}%;height:${(bottom - top) * 100}%`;
    }

    async detectCodes(file) {
        let nativeDecoded = null;
        if ("BarcodeDetector" in window) {
            try {
                const supported = await window.BarcodeDetector.getSupportedFormats();
                const formats = BARCODE_FORMATS.filter((format) => supported.includes(format));
                if (formats.length) {
                    const detector = new window.BarcodeDetector({ formats });
                    const bitmap = await createImageBitmap(file);
                    try {
                        const detected = await detector.detect(bitmap);
                        nativeDecoded = detected.map((item) => ({
                            rawValue: item.rawValue,
                            format: item.format,
                        }));
                    } finally {
                        bitmap.close();
                    }
                }
            } catch {
                nativeDecoded = null;
            }
        }
        if (!nativeDecoded?.length) {
            this.state.decoded = await detectWithOdooZXing(file);
        } else {
            this.state.decoded = nativeDecoded;
        }
        const codes = this.state.decoded
            .filter((code) => gtinCheckDigitIsValid(code.rawValue, code.format))
            .map((code) => ({raw_value: code.rawValue, symbology: code.format}));
        if (codes.length) {
            const result = await this.orm.call(
                "mb.inventory.capture", "action_record_scans",
                [[this.state.captureId], codes],
            );
            if (result.ambiguous) {
                this.state.lookupState = "ambiguous";
                this.state.scanHint = _t("Several products were detected. Choose the correct product during review.");
                this.notification.add(this.state.scanHint, {type: "warning"});
            }
        }
    }

    async submitManualCode() {
        const value = this.state.manualCode.trim();
        if (!value) {
            return;
        }
        const captureId = await this.ensureCapture();
        await this.orm.call("mb.inventory.capture", "action_record_scan", [
            [captureId], value, "manual",
        ]);
        this.state.decoded.push({ rawValue: value, format: "manual" });
        this.state.manualCode = "";
    }

    async openReview() {
        const captureId = await this.ensureCapture();
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "mb.inventory.capture",
            res_id: captureId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async analyzeImages() {
        if (!this.state.captureId || !this.state.uploaded) {
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.orm.call("mb.inventory.capture", "action_prepare_extraction", [
                [this.state.captureId],
            ]);
            const manualOnly = result.outcome === "manual_only" || result.queued === false;
            this.notification.add(manualOnly
                ? _t("No extraction service is configured. Continue with manual review.")
                : _t("Image analysis was queued. Review the capture for results."), {
                type: manualOnly ? "warning" : "success",
            });
            await this.openReview();
        } catch (error) {
            this.notification.add(error.data?.message || error.message || _t("Analysis could not be queued."), {
                type: "danger",
            });
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("actions").add("mb_inventory_capture.capture", InventoryCaptureAction);
