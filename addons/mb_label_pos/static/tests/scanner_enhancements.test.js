import { expect, test } from "@odoo/hoot";
import { BarcodeVideoScanner } from "@web/core/barcode/barcode_video_scanner";
import { CropOverlay } from "@web/core/barcode/crop_overlay";
import {
    defaultSquarePoint, selectBrightnessCapability,
} from "@mb_label_pos/scanner_enhancements";

test("label POS camera scan zone defaults to a centered square", () => {
    const point = defaultSquarePoint(400, 800);
    const marginX = 400 - point.x;
    const marginY = 800 - point.y;
    expect(400 - 2 * marginX).toBe(288);
    expect(800 - 2 * marginY).toBe(288);
});

test("square crop remains an opt-in scanner prop", () => {
    expect(BarcodeVideoScanner.props.mbLabelSquareCrop.optional).toBe(true);
    expect(CropOverlay.props.mbLabelSquareCrop.optional).toBe(true);
    expect(BarcodeVideoScanner.defaultProps.mbLabelSquareCrop).toBe(undefined);
});

test("phone light controls prefer torch strength then exposure", () => {
    expect(selectBrightnessCapability({
        torchStrength: { min: 0.1, max: 1, step: 0.1 },
        exposureCompensation: { min: -2, max: 2, step: 0.5 },
    })).toEqual({ key: "torchStrength", min: 0.1, max: 1, step: 0.1 });
    expect(selectBrightnessCapability({
        exposureCompensation: { min: -2, max: 2, step: 0.5 },
    })).toEqual({ key: "exposureCompensation", min: -2, max: 2, step: 0.5 });
    expect(selectBrightnessCapability({ torch: true })).toBe(null);
});
