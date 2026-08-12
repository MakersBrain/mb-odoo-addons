/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import { bytesToBase64, consensusCandidate, gtinCheckDigitIsValid } from "../src/capture_action";

describe("mb_inventory_capture", () => {
test("binary upload encoding preserves every byte", () => {
    expect(bytesToBase64(new Uint8Array([0, 1, 127, 128, 255]).buffer)).toBe("AAF/gP8=");
});

test("GTIN validation rejects a bad check digit", () => {
    expect(gtinCheckDigitIsValid("097539118054")).toBe(true);
    expect(gtinCheckDigitIsValid("097539118055")).toBe(false);
    expect(gtinCheckDigitIsValid("04252614", "upc_e")).toBe(true);
    expect(gtinCheckDigitIsValid("04252615", "upc_e")).toBe(false);
    expect(gtinCheckDigitIsValid("(01)00097539118054(10)24111042", "data_matrix")).toBe(true);
});

test("live decoding requires two matching recent frames", () => {
    const now = 5000;
    expect(consensusCandidate([
        {rawValue: "097539118054", format: "upc_a", at: now - 300},
    ], now)).toBe(null);
    expect(consensusCandidate([
        {rawValue: "097539118054", format: "upc_a", at: now - 600},
        {rawValue: "097539118054", format: "upc_a", at: now - 100},
    ], now).rawValue).toBe("097539118054");
    expect(consensusCandidate([
        {rawValue: "097539118054", format: "upc_a", at: now - 3000},
        {rawValue: "097539118054", format: "upc_a", at: now - 100},
    ], now)).toBe(null);
});
});
