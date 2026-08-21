/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import {
    applyMediaPreset, applyPrinterProfile, matchingMediaId, PRINTER_PROFILES,
    printerProfile, printerProfileId,
} from "@mb_label/editor/printer_presets";
import { shouldClearWorkspaceSelection } from "@mb_label/editor/selection";
import { parseTemplateFile, serializeTemplateFile } from "@mb_label/editor/template_file";
import { formatTemplateText } from "@mb_label/editor/template_formatters";

const clone = (value) => JSON.parse(JSON.stringify(value));
const TYPES = ["text", "qr", "barcode", "image", "rect", "ellipse", "triangle", "line"];

function blankElement(type, index) {
    const base = { id: `element_${Date.now()}_${index}`, type, x: 2, y: 2, width: 15, height: 6, z: index };
    if (type === "text") return { ...base, text: "{{product.name}}", font_size: 3, width: 24 };
    if (type === "qr") return { ...base, data: "{{qr}}", width: 12, height: 12, quiet_zone: 0 };
    if (type === "barcode") return { ...base, data: "{{product.barcode}}", width: 28, height: 8 };
    if (type === "image") return { ...base, data: "", width: 15, height: 10 };
    if (type === "line") return { ...base, width: 20, height: 1, stroke_width: 0.25 };
    return { ...base, width: 20, height: 8, stroke_width: 0.25, filled: false };
}

export class LabelEditor extends Component {
    static template = "mb_label.LabelEditor";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            templates: [], selectedTemplateId: null, selectedElementId: null,
            selectedElementIds: [],
            document: { schema: 1, elements: [] }, undo: [], redo: [],
            zoom: 5, grid: true, saving: false, dirty: false,
            previewProducts: [], previewLots: [], previewProductId: null,
            previewLotId: null, previewValues: {}, previewOptionsLoaded: false,
        });
        this.drag = null;
        onWillStart(() => this.load());
    }

    async load(selectedId = null) {
        if (!this.state.previewOptionsLoaded) {
            const options = await this.orm.call("mb.label.template", "editor_preview_options", []);
            this.state.previewProducts = options.products;
            this.state.previewLots = options.lots;
            this.state.previewOptionsLoaded = true;
        }
        this.state.templates = await this.orm.call("mb.label.template", "editor_bootstrap", []);
        const template = this.state.templates.find((item) => item.id === selectedId)
            || this.state.templates.find((item) => item.id === this.state.selectedTemplateId)
            || this.state.templates[0];
        if (template) this.selectTemplate(template.id);
    }

    get template() {
        return this.state.templates.find((item) => item.id === this.state.selectedTemplateId);
    }

    get selected() {
        return this.state.document.elements.find((item) => item.id === this.state.selectedElementId);
    }

    get selectedElements() {
        return this.state.document.elements.filter((item) => this.state.selectedElementIds.includes(item.id));
    }

    get previewLots() {
        return this.state.previewLots.filter((lot) => lot.product_id === this.state.previewProductId);
    }

    templateOptionLabel(item) {
        return _t("%(name)s · v%(version)s", { name: item.name, version: item.version_number });
    }

    get canvasSizeSummary() {
        return _t("%(width)s × %(height)s mm · %(dpi)s dpi", {
            width: this.template.width_mm,
            height: this.template.height_mm,
            dpi: this.template.dpi,
        });
    }

    printerProfileLabel(profile) {
        return _t("%(name)s · %(dpi)s dpi", { name: profile.label, dpi: profile.dpi });
    }

    get types() { return TYPES; }

    get printerProfiles() { return PRINTER_PROFILES; }

    get selectedPrinterProfileId() {
        return printerProfileId(this.template?.printer_target);
    }

    get selectedPrinterProfile() {
        return printerProfile(this.selectedPrinterProfileId);
    }

    get selectedMediaPresetId() {
        return matchingMediaId(this.template || {}, this.selectedPrinterProfile);
    }

    selectTemplate(id) {
        if (this.state.dirty && !window.confirm(_t("Discard unsaved label changes?"))) return;
        const template = this.state.templates.find((item) => item.id === Number(id));
        if (!template) return;
        this.state.selectedTemplateId = template.id;
        this.state.document = clone(template.document);
        this.state.selectedElementId = null;
        this.state.selectedElementIds = [];
        this.state.undo = [];
        this.state.redo = [];
        this.state.dirty = false;
        if (this.state.previewProductId) this.refreshPreview();
    }

    onTemplateSelect(event) { this.selectTemplate(event.target.value); }

    async onPreviewProduct(event) {
        this.state.previewProductId = Number(event.target.value) || null;
        this.state.previewLotId = null;
        await this.refreshPreview();
    }

    async onPreviewLot(event) {
        this.state.previewLotId = Number(event.target.value) || null;
        await this.refreshPreview();
    }

    async refreshPreview() {
        if (!this.state.previewProductId) {
            this.state.previewValues = {};
            return;
        }
        this.state.previewValues = await this.orm.call(
            "mb.label.template", "editor_preview_bindings", [], {
                product_id: this.state.previewProductId,
                lot_id: this.state.previewLotId || false,
                qr_url_prefix: this.template?.qr_url_prefix || "",
            });
    }

    snapshot() {
        this.state.undo.push(clone(this.state.document));
        if (this.state.undo.length > 100) this.state.undo.shift();
        this.state.redo = [];
    }

    changed() { this.state.dirty = true; }

    patchTemplateField(event) {
        if (!this.template) return;
        this.template[event.target.name] = event.target.type === "checkbox"
            ? event.target.checked : event.target.type === "number"
                ? Number(event.target.value) : event.target.value;
        this.changed();
        if (event.target.name === "qr_url_prefix") this.refreshPreview();
    }

    onPrinterProfile(event) {
        if (!this.template) return;
        Object.assign(this.template, applyPrinterProfile(this.template, event.target.value));
        this.changed();
    }

    onMediaPreset(event) {
        const media = this.selectedPrinterProfile?.media.find((item) => item.id === event.target.value);
        if (!this.template || !media) return;
        Object.assign(this.template, applyMediaPreset(this.template, media));
        this.changed();
    }

    undo() {
        const previous = this.state.undo.pop();
        if (!previous) return;
        this.state.redo.push(clone(this.state.document));
        this.state.document = previous;
        this.changed();
    }

    redo() {
        const next = this.state.redo.pop();
        if (!next) return;
        this.state.undo.push(clone(this.state.document));
        this.state.document = next;
        this.changed();
    }

    add(type) {
        this.snapshot();
        const element = blankElement(type, this.state.document.elements.length + 1);
        this.state.document.elements.push(element);
        this.state.selectedElementId = element.id;
        this.state.selectedElementIds = [element.id];
        this.changed();
    }

    selectElement(id, event) {
        event?.stopPropagation();
        const element = this.state.document.elements.find((item) => item.id === id);
        if (!element) return;
        const related = element.group_id
            ? this.state.document.elements.filter((item) => item.group_id === element.group_id).map((item) => item.id)
            : [id];
        if (event?.shiftKey || event?.ctrlKey || event?.metaKey) {
            const selected = new Set(this.state.selectedElementIds);
            const remove = related.every((itemId) => selected.has(itemId));
            for (const itemId of related) remove ? selected.delete(itemId) : selected.add(itemId);
            this.state.selectedElementIds = [...selected];
        } else {
            this.state.selectedElementIds = related;
        }
        this.state.selectedElementId = id;
    }

    clearSelection(event) {
        if (!shouldClearWorkspaceSelection(event)) return;
        this.state.selectedElementId = null;
        this.state.selectedElementIds = [];
    }

    remove() {
        if (!this.selectedElements.length) return;
        this.snapshot();
        const selected = new Set(this.state.selectedElementIds);
        this.state.document.elements = this.state.document.elements.filter((item) => !selected.has(item.id));
        this.clearSelection();
        this.changed();
    }

    reorder(direction) {
        if (!this.selectedElements.length) return;
        this.snapshot();
        const zValues = this.state.document.elements.map((item) => Number(item.z || 0));
        const edge = direction > 0 ? Math.max(...zValues, 0) : Math.min(...zValues, 0);
        this.selectedElements.forEach((element, index) => {
            element.z = edge + direction * (index + 1);
        });
        this.changed();
    }

    duplicate() {
        if (!this.selectedElements.length) return;
        this.snapshot();
        const groupId = this.selectedElements.length > 1 ? `group_${Date.now()}` : null;
        const copies = this.selectedElements.map((source, index) => ({
            ...clone(source), id: `element_${Date.now()}_${index}`,
            x: source.x + 1, y: source.y + 1,
            z: this.state.document.elements.length + index + 1,
            group_id: groupId || source.group_id,
        }));
        this.state.document.elements.push(...copies);
        this.state.selectedElementId = copies[0].id;
        this.state.selectedElementIds = copies.map((item) => item.id);
        this.changed();
    }

    group() {
        if (this.selectedElements.length < 2) return;
        this.snapshot();
        const groupId = `group_${Date.now()}`;
        for (const element of this.selectedElements) element.group_id = groupId;
        this.changed();
    }

    ungroup() {
        if (!this.selectedElements.length) return;
        this.snapshot();
        for (const element of this.selectedElements) delete element.group_id;
        this.changed();
    }

    patchField(event) {
        const element = this.selected;
        if (!element) return;
        this.snapshot();
        const key = event.target.name;
        const value = event.target.type === "checkbox" ? event.target.checked
            : event.target.type === "number" || key === "quiet_zone"
                ? Number(event.target.value) : event.target.value;
        const geometry = new Set(["x", "y", "width", "height"]);
        const targets = geometry.has(key) ? [element] : this.selectedElements;
        for (const target of targets) {
            target[key] = value;
            if (target.type === "qr" && (key === "width" || key === "height")) {
                target.width = value;
                target.height = value;
            }
        }
        this.changed();
    }

    beginDrag(event, id) {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        if (!this.state.selectedElementIds.includes(id)) this.selectElement(id);
        this.snapshot();
        const element = this.selected;
        const canvas = event.currentTarget.parentElement;
        this.drag = {
            mode: "move",
            startX: event.clientX, startY: event.clientY, x: element.x, y: element.y,
            pxPerMm: canvas.getBoundingClientRect().width / this.template.width_mm,
            positions: this.selectedElements.map((item) => ({ id: item.id, x: item.x, y: item.y })),
        };
        const move = (moveEvent) => this.moveDrag(moveEvent);
        const up = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            this.drag = null;
            this.changed();
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up, { once: true });
    }

    moveDrag(event) {
        if (!this.drag || !this.selected) return;
        const step = this.state.grid ? 0.5 : 0.1;
        const snap = (value) => Math.round(value / step) * step;
        if (this.drag.mode === "resize") {
            const dx = (event.clientX - this.drag.startX) / this.drag.pxPerMm;
            const dy = (event.clientY - this.drag.startY) / this.drag.pxPerMm;
            if (this.selected.type === "qr") {
                const delta = Math.abs(dx) >= Math.abs(dy) ? dx : dy;
                const size = Math.max(0.5, snap(this.drag.size + delta));
                this.selected.width = size;
                this.selected.height = size;
            } else {
                this.selected.width = Math.max(0.5, snap(this.drag.width + dx));
                this.selected.height = Math.max(0.5, snap(this.drag.height + dy));
            }
        } else {
            const dx = (event.clientX - this.drag.startX) / this.drag.pxPerMm;
            const dy = (event.clientY - this.drag.startY) / this.drag.pxPerMm;
            for (const position of this.drag.positions) {
                const element = this.state.document.elements.find((item) => item.id === position.id);
                if (!element) continue;
                element.x = Math.max(0, snap(position.x + dx));
                element.y = Math.max(0, snap(position.y + dy));
            }
        }
    }

    beginResize(event, id) {
        event.preventDefault();
        event.stopPropagation();
        this.selectElement(id);
        this.snapshot();
        const canvas = event.currentTarget.closest(".o_mb_label_canvas");
        this.drag = {
            mode: "resize", startX: event.clientX, startY: event.clientY,
            width: this.selected.width, height: this.selected.height,
            size: Math.max(this.selected.width, this.selected.height),
            pxPerMm: canvas.getBoundingClientRect().width / this.template.width_mm,
        };
        const move = (moveEvent) => this.moveDrag(moveEvent);
        const up = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            this.drag = null;
            this.changed();
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up, { once: true });
    }

    onCanvasKeydown(event) {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
            event.preventDefault();
            return event.shiftKey ? this.redo() : this.undo();
        }
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
            event.preventDefault(); return this.redo();
        }
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d") {
            event.preventDefault(); return this.duplicate();
        }
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
            event.preventDefault();
            this.state.selectedElementIds = this.state.document.elements.map((item) => item.id);
            this.state.selectedElementId = this.state.selectedElementIds[0] || null;
            return;
        }
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "g") {
            event.preventDefault(); return event.shiftKey ? this.ungroup() : this.group();
        }
        if (event.key === "Escape") {
            event.preventDefault(); return this.clearSelection();
        }
        if (!this.selected) return;
        if (event.key === "Delete" || event.key === "Backspace") {
            event.preventDefault(); return this.remove();
        }
        const directions = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
        const direction = directions[event.key];
        if (!direction) return;
        event.preventDefault();
        this.snapshot();
        const step = event.shiftKey ? 0.1 : 0.5;
        for (const element of this.selectedElements) {
            element.x = Math.max(0, element.x + direction[0] * step);
            element.y = Math.max(0, element.y + direction[1] * step);
        }
        this.changed();
    }

    uploadImage(event) {
        const file = event.target.files?.[0];
        if (!file || !this.selected || this.selected.type !== "image") return;
        if (!file.type.startsWith("image/") || file.size > 2 * 1024 * 1024) {
            this.notification.add(_t("Choose an image smaller than 2 MB."), { type: "warning" });
            return;
        }
        const reader = new FileReader();
        reader.onload = () => {
            this.snapshot();
            this.selected.data = reader.result;
            this.changed();
        };
        reader.readAsDataURL(file);
    }

    pasteImage(event) {
        const file = [...(event.clipboardData?.files || [])].find((item) => item.type.startsWith("image/"));
        if (!file || file.size > 2 * 1024 * 1024) return;
        event.preventDefault();
        const reader = new FileReader();
        reader.onload = () => {
            this.add("image");
            this.selected.data = reader.result;
            this.selected.dither = "threshold";
            this.selected.dither_threshold = 160;
            this.changed();
        };
        reader.readAsDataURL(file);
    }

    elementStyle(element) {
        return [
            `left:${element.x}mm`, `top:${element.y}mm`, `width:${element.width}mm`,
            `height:${Math.max(element.height, 0.3)}mm`, `z-index:${element.z || 0}`,
            `transform:rotate(${element.rotation || 0}deg)`,
            `font-size:${element.font_size || 3}mm`,
            `font-family:${element.font === "mono" ? "monospace" : element.font === "serif" ? "serif" : "sans-serif"}`,
            `font-weight:${element.bold ? "700" : "400"}`,
            `font-style:${element.italic ? "italic" : "normal"}`,
            `text-decoration:${element.underline ? "underline" : "none"}`,
            `text-align:${element.align || "left"}`,
            `background:${element.background === "black" ? "#111" : element.background === "white" ? "#fff" : "transparent"}`,
            `color:${element.inverted ? "#fff" : "#111"}`,
        ].join(";");
    }

    elementText(element) {
        const fallback = {
            "product.name": _t("Glazed stoneware mug"), "product.price": "45.00 €",
            "product.price.raw": 45, "company.currency": "EUR",
            "product.default_code": "MUG-001", "product.barcode": "3760000000000",
            "lot.name": "LOT-2026-08", "company.name": _t("Workshop"),
            "qr.path": "MUG-001/LOT-2026-08",
            qr: `${this.template?.qr_url_prefix || "https://example.com/profile"}#MUG-001/LOT-2026-08`,
        };
        const values = { ...fallback, ...this.state.previewValues };
        return formatTemplateText(element.text || element.data || element.type, values);
    }

    async createTemplate() {
        const ids = await this.orm.create("mb.label.template", [{
            name: _t("New 40 x 30 mm label"), width_mm: 40, height_mm: 30, dpi: 203,
        }]);
        await this.orm.call("mb.label.template", "save_version", [ids, { schema: 1, elements: [] }, "{{qr}}"]);
        await this.load(ids[0]);
    }

    async importJson(event) {
        const file = event.target.files?.[0];
        event.target.value = "";
        if (!file) return;
        if (file.size > 5 * 1024 * 1024) {
            this.notification.add(_t("The JSON file must be smaller than 5 MB."), { type: "warning" });
            return;
        }
        try {
            const imported = parseTemplateFile(
                JSON.parse(await file.text()), file.name.replace(/\.json$/i, ""));
            const ids = await this.orm.create("mb.label.template", [{
                name: imported.name,
                width_mm: imported.settings.width_mm,
                height_mm: imported.settings.height_mm,
                dpi: imported.settings.dpi,
                printer_target: imported.settings.printer_target,
                round_media: imported.settings.round_media,
                continuous_media: imported.settings.continuous_media,
            }]);
            await this.orm.call("mb.label.template", "save_editor_version", [
                ids, imported.document, imported.settings,
            ]);
            await this.load(ids[0]);
            this.notification.add(_t("The label template was imported as immutable version 1."), {
                type: "success",
            });
        } catch (error) {
            this.notification.add(error.message || _t("The JSON label could not be imported."), { type: "danger" });
        }
    }

    exportJson() {
        if (!this.template) return;
        const payload = serializeTemplateFile(this.template, this.state.document);
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${this.template.name.replace(/[^\w.-]+/g, "-") || "label"}.json`;
        anchor.click();
        URL.revokeObjectURL(url);
    }

    async save() {
        if (!this.template || this.state.saving) return;
        this.state.saving = true;
        try {
            await this.orm.call("mb.label.template", "save_editor_version", [
                [this.template.id], clone(this.state.document), {
                    width_mm: Number(this.template.width_mm),
                    height_mm: Number(this.template.height_mm),
                    dpi: Number(this.template.dpi),
                    qr_payload_template: this.template.qr_payload_template || "{{qr}}",
                    qr_url_prefix: this.template.qr_url_prefix || "",
                    printer_target: this.template.printer_target || "",
                    round_media: Boolean(this.template.round_media),
                    continuous_media: Boolean(this.template.continuous_media),
                },
            ]);
            this.notification.add(_t("A new immutable label version was saved."), { type: "success" });
            this.state.dirty = false;
            await this.load(this.template.id);
        } catch (error) {
            this.notification.add(error.message || _t("The label could not be saved."), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }
}

registry.category("actions").add("mb_label.editor", LabelEditor);
