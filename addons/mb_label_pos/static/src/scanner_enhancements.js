/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { BarcodeVideoScanner } from "@web/core/barcode/barcode_video_scanner";
import { CropOverlay } from "@web/core/barcode/crop_overlay";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

const SQUARE_OVERLAY_KEY = "mb-pos-barcode-overlay-square-v1";

BarcodeVideoScanner.props.mbLabelSquareCrop = { type: Boolean, optional: true };
CropOverlay.props.mbLabelSquareCrop = { type: Boolean, optional: true };

function bounded(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
}

export function defaultSquarePoint(width, height, ratio = 0.72) {
    const side = Math.max(1, Math.min(width, height) * ratio);
    const marginX = (width - side) / 2;
    const marginY = (height - side) / 2;
    return {
        x: width - marginX,
        y: height - marginY,
    };
}

export function selectBrightnessCapability(capabilities = {}) {
    for (const key of ["torchStrength", "exposureCompensation", "brightness"]) {
        const range = capabilities[key];
        if (
            range
            && Number.isFinite(Number(range.min))
            && Number.isFinite(Number(range.max))
            && Number(range.max) > Number(range.min)
        ) {
            const minimum = Number(range.min);
            const maximum = Number(range.max);
            return {
                key,
                min: minimum,
                max: maximum,
                step: Number(range.step) > 0
                    ? Number(range.step) : Math.max((maximum - minimum) / 20, 0.01),
            };
        }
    }
    return null;
}

patch(CropOverlay.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.props.mbLabelSquareCrop) {
            // A separate key leaves Odoo's native scanner crop untouched.
            // The user can still drag the handle after initialisation.
            this.localStorageKey = SQUARE_OVERLAY_KEY;
        }
    },

    computeDefaultPoint() {
        if (!this.props.mbLabelSquareCrop) {
            return super.computeDefaultPoint(...arguments);
        }
        const style = getComputedStyle(this.cropContainerRef.el.firstChild);
        const width = Number.parseFloat(style.width) || this.cropContainerRef.el.clientWidth;
        const height = Number.parseFloat(style.height) || this.cropContainerRef.el.clientHeight;
        const stored = browser.localStorage.getItem(this.localStorageKey);
        if (stored) {
            try {
                const point = JSON.parse(stored);
                this.relativePosition = {
                    x: bounded(Number(point.x), 0, width),
                    y: bounded(Number(point.y), 0, height),
                };
                return;
            } catch {
                browser.localStorage.removeItem(this.localStorageKey);
            }
        }
        this.relativePosition = defaultSquarePoint(width, height);
    },
});

patch(BarcodeVideoScanner.prototype, {
    setup() {
        super.setup(...arguments);
        Object.assign(this.state, {
            torchSupported: false,
            torchEnabled: false,
            lightBusy: false,
            lightError: "",
            brightnessSupported: false,
            brightnessKey: "",
            brightnessMin: 0,
            brightnessMax: 1,
            brightnessStep: 0.05,
            brightnessValue: 0,
        });
    },

    async isVideoReady() {
        const ready = await super.isVideoReady(...arguments);
        if (ready) {
            await this.setupPhoneLightControls();
        }
        return ready;
    },

    videoTrack() {
        return this.stream?.getVideoTracks?.()[0] || null;
    },

    async setupPhoneLightControls() {
        const track = this.videoTrack();
        if (!track?.getCapabilities) return;
        const capabilities = track.getCapabilities() || {};
        const settings = track.getSettings?.() || {};
        this.state.torchSupported = capabilities.torch === true;
        this.state.torchEnabled = Boolean(settings.torch);
        const brightness = selectBrightnessCapability(capabilities);
        if (!brightness) return;
        this.state.brightnessSupported = true;
        this.state.brightnessKey = brightness.key;
        this.state.brightnessMin = brightness.min;
        this.state.brightnessMax = brightness.max;
        this.state.brightnessStep = brightness.step;
        this.state.brightnessValue = Number.isFinite(Number(settings[brightness.key]))
            ? Number(settings[brightness.key])
            : bounded(0, brightness.min, brightness.max);
    },

    async togglePhoneTorch() {
        const track = this.videoTrack();
        if (!track || this.state.lightBusy) return;
        this.state.lightBusy = true;
        this.state.lightError = "";
        const enabled = !this.state.torchEnabled;
        try {
            await track.applyConstraints({ advanced: [{ torch: enabled }] });
            this.state.torchEnabled = enabled;
        } catch (error) {
            this.state.lightError = _t("The camera rejected the flash setting: %(message)s", {
                message: error?.message || String(error),
            });
        } finally {
            this.state.lightBusy = false;
        }
    },

    async changeScanBrightness(event) {
        const track = this.videoTrack();
        const key = this.state.brightnessKey;
        if (!track || !key) return;
        const value = bounded(
            Number(event.currentTarget.value),
            this.state.brightnessMin,
            this.state.brightnessMax
        );
        this.state.brightnessValue = value;
        this.state.lightError = "";
        try {
            await track.applyConstraints({ advanced: [{ [key]: value }] });
        } catch (error) {
            this.state.lightError = _t("The camera rejected the brightness setting: %(message)s", {
                message: error?.message || String(error),
            });
        }
    },
});
