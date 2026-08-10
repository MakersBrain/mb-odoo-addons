/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { bytesToBase64 } from "../src/capture_action";

test("binary upload encoding preserves every byte", () => {
    expect(bytesToBase64(new Uint8Array([0, 1, 127, 128, 255]).buffer)).toBe("AAF/gP8=");
});

