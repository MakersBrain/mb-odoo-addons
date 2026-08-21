/** @odoo-module **/

export function normalizeQr(value) {
    return String(value || "").normalize("NFKC").trim();
}

function normalizePrefix(value) {
    return normalizeQr(value).replace(/#+$/, "").replace(/\/$/, "");
}

export function matchesLabelPrefix(value, prefixes = []) {
    const normalized = normalizeQr(value);
    for (const rawPrefix of prefixes) {
        const prefix = normalizePrefix(rawPrefix);
        if (prefix && normalized.startsWith(`${prefix}#`)) return true;
    }
    return false;
}

function relationId(value) {
    if (Number.isInteger(value)) return value;
    if (Array.isArray(value)) return value[0];
    return value?.id;
}

export function buildAliasIndex(aliases = []) {
    const index = new Map();
    for (const alias of aliases) {
        const key = normalizeQr(alias.value);
        const values = index.get(key) || [];
        values.push(alias);
        index.set(key, values);
    }
    return index;
}

export function resolveLocalQr(value, { aliases = [], aliasIndex = null, prefixes = [] } = {}) {
    const normalized = normalizeQr(value);
    const exact = aliasIndex?.get(normalized)
        || aliases.filter((alias) => normalizeQr(alias.value) === normalized);
    if (exact.length === 1) {
        const alias = exact[0];
        if (alias.active === false) return { matched: true, status: "retired" };
        return {
            matched: true,
            status: "resolved",
            source: "alias",
            productId: relationId(alias.product_id),
            product: typeof alias.product_id === "object" && !Array.isArray(alias.product_id)
                ? alias.product_id : null,
            lotName: alias.lot_name || false,
            availableQuantity: alias.pos_available_quantity,
        };
    }

    if (matchesLabelPrefix(normalized, prefixes)) {
        return { matched: true, status: "online_lookup", source: "uncached" };
    }
    return { matched: false, status: "no_match" };
}

export function reconcileOnlineResolution(local, online) {
    if (online?.status === "offline") {
        return local.source === "alias"
            ? local : { ...local, status: "offline_lookup_required" };
    }
    if (online?.status === "resolved") {
        return {
            ...local,
            status: "resolved",
            productId: online.product_id,
            lotName: online.lot_name || false,
            availableQuantity: online.available_quantity,
        };
    }
    return { ...local, status: online?.status || "unresolved" };
}

export function validateDraftAvailability({
    tracking, lotName, draftLotCount = 0, draftQuantity = 0, availableQuantity,
}) {
    if (tracking === "serial" && lotName && draftLotCount > 0) return "duplicate_serial";
    if (Number.isFinite(availableQuantity) && availableQuantity <= draftQuantity) {
        return "out_of_stock";
    }
    return null;
}
