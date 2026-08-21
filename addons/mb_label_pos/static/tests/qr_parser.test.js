import { expect, test } from "@odoo/hoot";
import {
    buildAliasIndex, matchesLabelPrefix, reconcileOnlineResolution, resolveLocalQr,
    validateDraftAvailability,
} from "@mb_label_pos/qr_parser";

const prefix = "https://instagram.com/username";

test("recognizes configured label prefixes without interpreting the payload", () => {
    expect(matchesLabelPrefix(`${prefix}#MUG-001`, [prefix])).toBe(true);
    expect(matchesLabelPrefix(`${prefix}#MUG-001/PIECE%202026`, [prefix])).toBe(true);
});

test("does not consume ordinary native barcodes", () => {
    expect(matchesLabelPrefix("3760123456789", [prefix])).toBe(false);
});

test("exact active and retired aliases are authoritative offline", () => {
    const product = { id: 7, default_code: "MUG-001" };
    const base = { value: `${prefix}#MUG-001/PIECE-1`, product_id: product, lot_name: "PIECE-1" };
    expect(resolveLocalQr(base.value, { aliases: [{ ...base, active: true }] }).status).toBe("resolved");
    expect(resolveLocalQr(base.value, { aliases: [{ ...base, active: false }] }).status).toBe("retired");
});

test("normalized alias index provides constant-time exact lookup", () => {
    const alias = { id: 1, value: `  ${prefix}#MUG-001  `, active: true, product_id: 7 };
    const aliasIndex = buildAliasIndex([alias]);
    const result = resolveLocalQr(`${prefix}#MUG-001`, { aliasIndex });
    expect(result.status).toBe("resolved");
    expect(result.productId).toBe(7);
});

test("an uncached current label requires authoritative online lookup", () => {
    expect(resolveLocalQr(`${prefix}#MUG-002`, { prefixes: [prefix] })).toEqual({
        matched: true, status: "online_lookup", source: "uncached",
    });
});

test("offline uses the cached alias while reconnection applies authoritative retirement", () => {
    const local = {
        matched: true, status: "resolved", source: "alias", productId: 7, lotName: "SERIAL-1",
    };
    expect(reconcileOnlineResolution(local, { status: "offline" })).toEqual(local);
    expect(reconcileOnlineResolution(local, { status: "retired" }).status).toBe("retired");
    const uncached = { ...local, source: "uncached", status: "online_lookup" };
    expect(reconcileOnlineResolution(uncached, { status: "offline" }).status)
        .toBe("offline_lookup_required");
});

test("draft stock validation rejects duplicate serials and exhausted batches", () => {
    expect(validateDraftAvailability({
        tracking: "serial", lotName: "S1", draftLotCount: 1,
        draftQuantity: 1, availableQuantity: 1,
    })).toBe("duplicate_serial");
    expect(validateDraftAvailability({
        tracking: "lot", lotName: "B1", draftLotCount: 1,
        draftQuantity: 3, availableQuantity: 3,
    })).toBe("out_of_stock");
    expect(validateDraftAvailability({
        tracking: "lot", lotName: "B1", draftLotCount: 1,
        draftQuantity: 2, availableQuantity: 3,
    })).toBe(null);
});
