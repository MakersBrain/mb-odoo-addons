/** @odoo-module **/

function numericValue(value) {
	if (typeof value === "number") return Number.isFinite(value) ? value : null;
	let source = String(value ?? "").replace(/[^\d,.-]/g, "");
	if (!source) return null;
	const comma = source.lastIndexOf(",");
	const dot = source.lastIndexOf(".");
	if (comma >= 0 && dot >= 0) {
		const decimal = comma > dot ? "," : ".";
		source = source.replace(decimal === "," ? /\./g : /,/g, "").replace(decimal, ".");
	} else if (comma >= 0) {
		source = source.replace(",", ".");
	}
	const numeric = Number(source);
	return Number.isFinite(numeric) ? numeric : null;
}

function formatMoney(value, currency, trimZeros) {
	if (trimZeros && typeof value === "string" && /[^\d\s.,+-]/.test(value)) {
		return value.replace(/([,.])00(?=(?:\s|[^\d])*$)/, "");
	}
	const numeric = numericValue(value);
	if (numeric === null) {
		const text = String(value ?? "");
		return trimZeros ? text.replace(/([,.])00(?=(?:\s|[^\d])*$)/, "") : text;
	}
	const integer = Number.isInteger(numeric);
	return new Intl.NumberFormat(undefined, {
		style: "currency", currency: currency || "EUR",
		minimumFractionDigits: trimZeros && integer ? 0 : 2,
		maximumFractionDigits: 2,
	}).format(numeric);
}

export function formatBindingValue(value, filterSource, values = {}) {
	for (const raw of String(filterSource || "").split("|").slice(1)) {
		const [rawName, ...argumentParts] = raw.trim().split(":");
		const name = rawName.toLowerCase();
		const argument = argumentParts.join(":");
		if (name === "default" && (value === null || value === undefined || value === "")) value = argument;
		else if (name === "trim") value = String(value ?? "").trim();
		else if (name === "upper") value = String(value ?? "").toUpperCase();
		else if (name === "lower") value = String(value ?? "").toLowerCase();
		else if (name === "title") value = String(value ?? "").toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
		else if (name === "money") value = formatMoney(value, values["company.currency"], false);
		else if (name === "money_trim") value = formatMoney(value, values["company.currency"], true);
		else if (name === "number") {
			const numeric = numericValue(value);
			if (numeric !== null) value = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(numeric);
		} else if (name === "fixed") {
			const numeric = numericValue(value);
			const digits = Math.max(0, Math.min(4, Number(argument) || 0));
			if (numeric !== null) value = new Intl.NumberFormat(undefined, {
				minimumFractionDigits: digits, maximumFractionDigits: digits,
			}).format(numeric);
		}
	}
	return String(value ?? "");
}

export function formatTemplateText(source, values = {}) {
	return String(source || "").replace(
		/\{\{\s*([\w.-]+)\s*((?:\|[^{}]*)?)\}\}/g,
		(token, key, filters) => key in values || filters.includes("|default:")
			? formatBindingValue(values[key], filters, values) : token);
}
