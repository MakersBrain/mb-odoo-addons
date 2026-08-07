/** @odoo-module **/

const SUPPORTED_TYPES = new Set([
	"text", "qr", "barcode", "image", "rect", "ellipse", "triangle", "line",
]);
const FIELD_BINDINGS = {
	name: "product.name",
	price: "product.price",
	ref: "product.default_code",
	batch: "lot.name",
	qr: "qr",
	"core.product.title": "product.name",
	"core.product.name": "product.name",
	"core.product.price": "product.price",
	"core.product.sku": "product.default_code",
	"core.identifier.qr": "qr",
	"core.production_lot.code": "lot.name",
};

const clone = (value) => JSON.parse(JSON.stringify(value));

function finite(value, fallback = 0) {
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : fallback;
}

function snakeFont(value = "") {
	const font = String(value).toLowerCase();
	if (font.includes("mono") || font.includes("courier")) return "mono";
	if (font.includes("sans")) return "sans";
	if (font.includes("serif") || font.includes("georgia") || font.includes("times")) return "serif";
	return "sans";
}

function elementType(raw) {
	if (raw.type === "shape" || raw.shapeType) {
		const shape = String(raw.shapeType || "rectangle").toLowerCase();
		if (shape.startsWith("ellip") || shape.startsWith("circ")) return "ellipse";
		if (shape.startsWith("tri")) return "triangle";
		if (shape.startsWith("line")) return "line";
		return "rect";
	}
	return SUPPORTED_TYPES.has(raw.type) ? raw.type : "text";
}

function thermalFill(raw) {
	const fill = String(raw.fill || "").toLowerCase();
	if (!fill) return { filled: Boolean(raw.filled), tint: raw.tint };
	if (fill === "none") return { filled: false };
	if (fill === "white" && raw.stroke && raw.stroke !== "none") return { filled: false };
	const tint = fill.includes("light") ? "25"
		: fill.includes("medium") ? "50" : fill.includes("dark") ? "75" : undefined;
	return { filled: true, tint, inverted: fill === "white" || undefined };
}

function fieldExpressions(fields = [], warnings = []) {
	const expressions = { ...FIELD_BINDINGS };
	for (const field of fields) {
		const key = String(field?.key || "").trim();
		if (!key) continue;
		if (field.source === "manual") {
			expressions[key] = `manual.${key.replace(/[^A-Za-z0-9_-]/g, "_")}`;
		} else if (field.source === "composed" && field.template) {
			expressions[key] = String(field.template);
		} else if (field.binding && FIELD_BINDINGS[field.binding]) {
			expressions[key] = FIELD_BINDINGS[field.binding];
		} else if (FIELD_BINDINGS[key]) {
			expressions[key] = FIELD_BINDINGS[key];
		} else {
			expressions[key] = `manual.${key.replace(/[^A-Za-z0-9_-]/g, "_")}`;
			warnings.push(`Field “${key}” was imported as a manual value.`);
		}
	}
	return expressions;
}

function translateBindings(source, expressions, warnings) {
	let translated = String(source || "");
	for (let pass = 0; pass < 4; pass++) {
		const next = translated.replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (token, key) => {
			const expression = expressions[key];
			if (!expression) {
				if (["product.name", "product.price", "product.default_code", "product.barcode", "lot.name", "company.name", "qr", "qr.path"].includes(key) || key.startsWith("manual.")) {
					return token;
				}
				const manual = `manual.${key.replace(/[^A-Za-z0-9_-]/g, "_")}`;
				expressions[key] = manual;
				warnings.push(`Binding “${key}” was imported as “${manual}”.`);
				return `{{${manual}}}`;
			}
			return expression.includes("{{") ? expression : `{{${expression}}}`;
		});
		if (next === translated) break;
		translated = next;
	}
	return translated;
}

function convertElement(raw, index, dpm, expressions, warnings) {
	const type = elementType(raw);
	if (!SUPPORTED_TYPES.has(raw.type) && raw.type !== "shape" && !raw.shapeType) {
		warnings.push(`Unknown element type “${raw.type || "empty"}” became text.`);
	}
	const mm = (value) => finite(value) / dpm;
	const element = {
		id: String(raw.id || `imported_${Date.now()}_${index}`),
		type,
		x: mm(raw.x),
		y: mm(raw.y),
		width: Math.max(0, mm(raw.width)),
		height: Math.max(0, mm(raw.height)),
		z: finite(raw.z, index),
	};
	if (raw.groupId || raw.group_id) element.group_id = String(raw.groupId || raw.group_id);
	if (raw.rotation) element.rotation = finite(raw.rotation);
	if (["white", "black", "transparent"].includes(raw.background)) {
		element.background = raw.background;
	}
	if (raw.inverted || raw.color === "white") element.inverted = true;
	if (raw.required === false || raw.optional === true) element.required = false;

	if (type === "text") {
		element.text = translateBindings(raw.text, expressions, warnings);
		element.font_size = Math.max(0.5, mm(raw.fontSize ?? raw.font_size ?? 14));
		element.bold = Boolean(raw.bold || raw.fontWeight === "bold" || finite(raw.fontWeight) >= 600);
		element.italic = Boolean(raw.italic || raw.fontStyle === "italic");
		element.underline = Boolean(raw.underline || String(raw.textDecoration || "").includes("underline"));
		element.font = raw.font || snakeFont(raw.fontFamily);
		element.align = raw.align || "left";
		element.valign = raw.valign || raw.verticalAlign || "middle";
		element.no_wrap = Boolean(raw.noWrap || raw.no_wrap);
	} else if (type === "qr" || type === "barcode") {
		element.data = translateBindings(raw.qrData ?? raw.data ?? "{{qr}}", expressions, warnings);
		if (raw.format) element.format = raw.format;
		element.show_value = Boolean(raw.showValue || raw.show_value);
		if (type === "qr") element.quiet_zone = Math.max(0, Math.min(8,
			Math.round(finite(raw.quietZone ?? raw.quiet_zone, 0))));
	} else if (type === "image") {
		element.data = raw.imageData || raw.data || "";
		element.pre_binarised = Boolean(raw.preBinarised || raw.pre_binarised);
		element.dither = raw.dither || "threshold";
		element.dither_threshold = finite(raw.ditherThreshold ?? raw.dither_threshold, 160);
		if (raw.assetUid) warnings.push(`Image ${element.id} used an external brand asset; embed it before importing.`);
	} else {
		Object.assign(element, thermalFill(raw));
		element.stroke_width = Math.max(0.1, mm(raw.strokeWidth ?? raw.stroke_width ?? 2));
	}
	return element;
}

export function importLegacyTemplate(raw, fallbackName = "Imported label") {
	if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
		throw new Error("The label JSON must contain one object.");
	}
	if (raw.schema === 1 && Array.isArray(raw.elements)) {
		return {
			name: fallbackName,
			document: clone(raw),
			settings: { width_mm: 40, height_mm: 30, dpi: 203 },
			warnings: [],
		};
	}
	const warnings = [];
	const dpm = finite(raw.dotsPerMm ?? raw.dots_per_mm, 8);
	if (dpm <= 0) throw new Error("The label resolution must be greater than zero.");
	const fields = Array.isArray(raw.fields) ? raw.fields : [];
	const expressions = fieldExpressions(fields, warnings);
	const sourceElements = Array.isArray(raw.elements) ? raw.elements : [];
	const width = finite(raw.widthMm ?? raw.width_mm ?? raw.labelSize?.width, 30);
	const height = finite(raw.heightMm ?? raw.height_mm ?? raw.labelSize?.height, 20);
	if (width <= 0 || height <= 0) throw new Error("The imported label needs positive dimensions.");
	return {
		name: String(raw.name || fallbackName || "Imported label"),
		document: {
			schema: 1,
			elements: sourceElements.map((element, index) =>
				convertElement(element || {}, index, dpm, expressions, warnings)),
		},
		settings: {
			width_mm: width,
			height_mm: height,
			dpi: Math.max(72, Math.min(600, Math.round(dpm * 25.4))),
			printer_target: String(raw.target || ""),
			round_media: Boolean(raw.round ?? raw.labelSize?.round),
			continuous_media: Boolean(raw.continuous ?? raw.labelSize?.continuous),
		},
		warnings: [...new Set(warnings)],
	};
}

export function exportLegacyTemplate(template, document) {
	const dpm = finite(template.dpi, 203) / 25.4;
	const dots = (value) => Math.round(finite(value) * dpm * 1000) / 1000;
	const elements = (document.elements || []).map((element) => {
		const output = {
			id: element.id,
			type: element.type,
			x: dots(element.x), y: dots(element.y),
			width: dots(element.width), height: dots(element.height),
			rotation: element.rotation || 0,
			groupId: element.group_id,
			background: element.background,
			inverted: Boolean(element.inverted),
			required: element.required !== false,
		};
		if (element.type === "text") Object.assign(output, {
			text: element.text || "", fontSize: dots(element.font_size || 3),
			bold: Boolean(element.bold), italic: Boolean(element.italic),
			underline: Boolean(element.underline), font: element.font || "sans",
			align: element.align || "left", valign: element.valign || "middle",
			noWrap: Boolean(element.no_wrap),
		});
		else if (["qr", "barcode"].includes(element.type)) Object.assign(output, {
			qrData: element.data || "", format: element.format,
			showValue: Boolean(element.show_value),
			quietZone: element.type === "qr" ? finite(element.quiet_zone, 0) : undefined,
		});
		else if (element.type === "image") Object.assign(output, {
			imageData: element.data || "", preBinarised: Boolean(element.pre_binarised),
			dither: element.dither || "threshold", ditherThreshold: finite(element.dither_threshold, 160),
		});
		else Object.assign(output, {
			filled: Boolean(element.filled), tint: element.tint,
			strokeWidth: dots(element.stroke_width || 0.25),
		});
		return Object.fromEntries(Object.entries(output).filter(([, value]) => value !== undefined));
	});
	return {
		name: template.name,
		version: 3,
		labelSize: {
			width: finite(template.width_mm), height: finite(template.height_mm),
			round: Boolean(template.round_media), continuous: Boolean(template.continuous_media),
		},
		widthMm: finite(template.width_mm),
		heightMm: finite(template.height_mm),
		dotsPerMm: dpm,
		target: template.printer_target || undefined,
		round: Boolean(template.round_media),
		continuous: Boolean(template.continuous_media),
		isTemplate: true,
		fields: [],
		elements,
		exportedAt: new Date().toISOString(),
	};
}
