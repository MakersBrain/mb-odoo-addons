/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { useBarcodeReader } from "@point_of_sale/app/hooks/barcode_reader_hook";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import {
    buildAliasIndex, reconcileOnlineResolution, resolveLocalQr,
    validateDraftAvailability,
} from "./qr_parser";

const ERROR_MESSAGES = {
    ambiguous: _t("This QR code matches more than one product or identity."),
    retired: _t("This printed QR identity has been retired and cannot be sold."),
    not_available: _t("The product identified by this label is not available in this Point of Sale."),
    out_of_stock: _t("This product, lot, or serial has no available stock in the POS source location."),
    duplicate_serial: _t("This serial number is already present in a draft POS order."),
    wrong_company: _t("This label belongs to another company."),
    offline_lookup_required: _t("This QR is not cached yet. Reconnect once to validate it."),
};

patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.mbLabelOrm = useService("orm");
        this.mbLabelAliasCache = { signature: null, index: new Map() };
        // A nomenclature with no catch-all product rule returns `error`.
        // Registering it keeps prefixed label URLs working in either setup.
        useBarcodeReader({ error: this._mbLabelErrorBarcodeAction });
    },

    get barcodeVideoScannerProps() {
        return {
            ...super.barcodeVideoScannerProps,
            mbLabelSquareCrop: true,
        };
    },

    _mbLabelCollections() {
        const aliases = this.pos.models["mb.label.qr.alias"]?.getAll() || [];
        const signature = aliases.map((alias) => `${alias.id}:${alias.active}:${alias.value}`).join("|");
        if (signature !== this.mbLabelAliasCache.signature) {
            this.mbLabelAliasCache = { signature, index: buildAliasIndex(aliases) };
        }
        return {
            aliases,
            aliasIndex: this.mbLabelAliasCache.index,
            prefixes: this.pos.config.mb_label_qr_prefixes || [],
        };
    },

    _mbLabelRawCode(code) {
        return code?.code || code?.base_code || "";
    },

    _mbLabelNotify(status) {
        this.sound.play("scan-error");
        this.notification.add(ERROR_MESSAGES[status] || _t("This label QR code could not be resolved."), {
            type: "danger",
            title: _t("Label QR error"),
        });
    },

    async _mbLabelOnlineResolve(raw) {
        try {
            return await this.mbLabelOrm.call(
                "mb.label.qr.alias", "pos_resolve", [raw, this.pos.config.id]);
        } catch {
            return { status: "offline" };
        }
    },

    async _mbLabelProduct(productId, current) {
        let product = current || this.pos.models["product.product"].get(productId);
        if (!product && productId) {
            await this.pos.loadNewProducts([["id", "=", productId]]);
            product = this.pos.models["product.product"].get(productId);
        }
        return product;
    },

    async _mbLabelAddResolution(resolution) {
        const product = await this._mbLabelProduct(resolution.productId, resolution.product);
        if (!product) {
            this._mbLabelNotify("not_available");
            return;
        }
        const draftLots = (this.pos.models["pos.pack.operation.lot"]?.getAll() || []).filter(
            (lot) => lot.lot_name === resolution.lotName
                && lot.pos_order_line_id?.product_id?.id === product.id
                && lot.pos_order_line_id?.order_id?.state === "draft");
        const draftQuantity = draftLots.reduce(
            (total, lot) => total + Math.abs(lot.pos_order_line_id?.qty || 0), 0);
        const availabilityError = validateDraftAvailability({
            tracking: product.tracking,
            lotName: resolution.lotName,
            draftLotCount: draftLots.length,
            draftQuantity,
            availableQuantity: resolution.availableQuantity,
        });
        if (availabilityError) {
            this._mbLabelNotify(availabilityError);
            return;
        }
        const vals = { product_id: product, product_tmpl_id: product.product_tmpl_id };
        if (product.tracking === "serial") vals.qty = 1;
        const options = {};
        if (resolution.lotName) {
            options.code = {
                type: "lot",
                code: resolution.lotName,
                base_code: resolution.lotName,
                value: resolution.lotName,
            };
        }
        this.sound.play("beep");
        await this.pos.addLineToCurrentOrder(vals, options, product.needToConfigure());
        this.numberBuffer.reset();
        this.showOptionalProductPopupIfNeeded(product);
    },

    async _tryMbLabelBarcode(code) {
        const raw = this._mbLabelRawCode(code);
        const collections = this._mbLabelCollections();
        let resolution = resolveLocalQr(raw, collections);
        if (!resolution.matched) return false;

        // The cached alias keeps scanning available offline. When online, the
        // authoritative lookup also catches aliases retired/reactivated after
        // this POS session loaded its projection.
        const online = await this._mbLabelOnlineResolve(raw);
        resolution = reconcileOnlineResolution(resolution, online);
        if (resolution.status !== "resolved") {
            this._mbLabelNotify(resolution.status);
            return true;
        }
        await this._mbLabelAddResolution(resolution);
        return true;
    },

    async _barcodeProductAction(code) {
        if (await this._tryMbLabelBarcode(code)) return;
        return super._barcodeProductAction(...arguments);
    },

    async _mbLabelErrorBarcodeAction(code) {
        if (await this._tryMbLabelBarcode(code)) return;
        this.barcodeReader.showNotFoundNotification(code);
    },
});

export {
    buildAliasIndex, reconcileOnlineResolution, resolveLocalQr,
    validateDraftAvailability,
};
