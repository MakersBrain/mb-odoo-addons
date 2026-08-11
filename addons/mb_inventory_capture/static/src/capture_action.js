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
        const result = reader.decode(new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(source)));
        const formatNames = new Map([
            [ZXing.BarcodeFormat.EAN_8, "ean_8"],
            [ZXing.BarcodeFormat.EAN_13, "ean_13"],
            [ZXing.BarcodeFormat.UPC_A, "upc_a"],
            [ZXing.BarcodeFormat.UPC_E, "upc_e"],
            [ZXing.BarcodeFormat.CODE_128, "code_128"],
            [ZXing.BarcodeFormat.QR_CODE, "qr_code"],
            [ZXing.BarcodeFormat.DATA_MATRIX, "data_matrix"],
        ]);
        return [{
            rawValue: result.getText(),
            format: formatNames.get(result.getBarcodeFormat()) || "unknown",
        }];
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
        });
        onWillUnmount(() => this.cleanup());
    }

    cleanup() {
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
                video: { facingMode: { ideal: "environment" } },
                audio: false,
            });
            this.video.el.srcObject = this.stream;
            await this.video.el.play();
            this.state.cameraActive = true;
        } catch {
            this.notification.add(_t("Camera permission was denied; use file upload."), {
                type: "warning",
            });
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
            await this.orm.call("mb.inventory.capture", "upload_image", [
                [captureId], bytesToBase64(buffer), this.state.role, file.name,
            ]);
            if (this.previewUrl) {
                URL.revokeObjectURL(this.previewUrl);
            }
            this.previewUrl = URL.createObjectURL(file);
            this.state.previewUrl = this.previewUrl;
            this.state.uploaded = true;
            await this.detectCodes(file);
        } catch (error) {
            this.notification.add(error.data?.message || error.message || _t("Upload failed."), {
                type: "danger",
            });
        } finally {
            this.state.busy = false;
        }
    }

    async detectCodes(file) {
        if (!("BarcodeDetector" in window)) {
            this.state.decoded = await detectWithOdooZXing(file);
        } else {
            const supported = await window.BarcodeDetector.getSupportedFormats();
            const formats = BARCODE_FORMATS.filter((format) => supported.includes(format));
            const detector = new window.BarcodeDetector({ formats });
            const bitmap = await createImageBitmap(file);
            try {
                const detected = await detector.detect(bitmap);
                this.state.decoded = detected.map((item) => ({
                    rawValue: item.rawValue,
                    format: item.format,
                }));
            } finally {
                bitmap.close();
            }
        }
        for (const code of this.state.decoded) {
            await this.orm.call("mb.inventory.capture", "action_record_scan", [
                [this.state.captureId], code.rawValue, code.format,
            ]);
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
            await this.orm.call("mb.inventory.capture", "action_prepare_extraction", [
                [this.state.captureId],
            ]);
            this.notification.add(_t("Image analysis was queued. Review the capture for results."), {
                type: "success",
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
