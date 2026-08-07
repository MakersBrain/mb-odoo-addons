import { expect, test } from "@odoo/hoot";
import {
    defaultSquarePoint, selectBrightnessCapability,
} from "@mb_label_pos/scanner_enhancements";

test("POS camera scan zone defaults to a centered square", () => {
    const point = defaultSquarePoint(400, 800);
    const marginX = 400 - point.x;
    const marginY = 800 - point.y;
    expect(400 - 2 * marginX).toBe(288);
    expect(800 - 2 * marginY).toBe(288);
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
