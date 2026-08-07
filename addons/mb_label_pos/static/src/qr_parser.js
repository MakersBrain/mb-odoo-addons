/** @odoo-module **/

export function normalizeQr(value) {
    return String(value || "").normalize("NFKC").trim();
}

function normalizePrefix(value) {
    return normalizeQr(value).replace(/#+$/, "").replace(/\/$/, "");
}

export function parsePrefixedQr(value, prefixes = []) {
    const normalized = normalizeQr(value);
    for (const rawPrefix of prefixes) {
        const prefix = normalizePrefix(rawPrefix);
        const marker = `${prefix}#`;
        if (!prefix || !normalized.startsWith(marker)) continue;
        const encodedParts = normalized.slice(marker.length).split("/");
        if (![1, 2].includes(encodedParts.length) || encodedParts.some((part) => !part)) {
            return { matched: true, status: "invalid" };
        }
        try {
            const [sku, lotName] = encodedParts.map((part) => decodeURIComponent(part).normalize("NFKC").trim());
            if (!sku || (encodedParts.length === 2 && !lotName)) {
                return { matched: true, status: "invalid" };
            }
            return { matched: true, status: "parsed", sku, lotName: lotName || false };
        } catch {
            return { matched: true, status: "invalid" };
        }
    }
    return { matched: false, status: "no_match" };
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

export function resolveLocalQr(
    value, { aliases = [], aliasIndex = null, products = [], prefixes = [] } = {}) {
    const normalized = normalizeQr(value);
    const exact = aliasIndex?.get(normalized)
        || aliases.filter((alias) => normalizeQr(alias.value) === normalized);
    if (exact.length > 1) return { matched: true, status: "ambiguous" };
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

    const parsed = parsePrefixedQr(normalized, prefixes);
    if (!parsed.matched || parsed.status !== "parsed") return parsed;
    const candidates = products.filter((product) => product.default_code === parsed.sku);
    if (candidates.length > 1) return { matched: true, status: "ambiguous" };
    if (!candidates.length) return { ...parsed, status: "online_lookup" };
    return {
        matched: true,
        status: "online_lookup",
        source: "compatibility-local",
        productId: candidates[0].id,
        product: candidates[0],
        lotName: parsed.lotName,
    };
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
