/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";

const clone = (value) => JSON.parse(JSON.stringify(value));

export function parseTemplateFile(raw, fallbackName = "Imported label") {
    if (!raw || typeof raw !== "object" || Array.isArray(raw) || raw.schema !== 1) {
        throw new Error(_t("Unsupported label template file schema."));
    }
    if (raw.document?.schema !== 1 || !Array.isArray(raw.document.elements)) {
        throw new Error(_t("The label template file has an invalid document."));
    }
    const settings = raw.settings;
    if (!settings || typeof settings !== "object" || Array.isArray(settings)) {
        throw new Error(_t("The label template file has no settings."));
    }
    const width = Number(settings.width_mm);
    const height = Number(settings.height_mm);
    const dpi = Number(settings.dpi);
    if (!(width > 0) || !(height > 0) || !(dpi > 0)) {
        throw new Error(_t("The label template dimensions and resolution must be positive."));
    }
    return {
        name: String(raw.name || fallbackName),
        document: clone(raw.document),
        settings: {
            width_mm: width,
            height_mm: height,
            dpi,
            printer_target: String(settings.printer_target || ""),
            round_media: Boolean(settings.round_media),
            continuous_media: Boolean(settings.continuous_media),
        },
    };
}

export function serializeTemplateFile(template, document) {
    return {
        schema: 1,
        name: template.name,
        settings: {
            width_mm: Number(template.width_mm),
            height_mm: Number(template.height_mm),
            dpi: Number(template.dpi),
            printer_target: template.printer_target || "",
            round_media: Boolean(template.round_media),
            continuous_media: Boolean(template.continuous_media),
        },
        document: clone(document),
    };
}
