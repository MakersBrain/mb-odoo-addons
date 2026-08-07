/** @odoo-module **/

const COMMON_MEDIA = [
	{ id: "40x30", label: "40 × 30 mm", width_mm: 40, height_mm: 30 },
	{ id: "30x20", label: "30 × 20 mm", width_mm: 30, height_mm: 20 },
	{ id: "round-20", label: "Round 20 mm", width_mm: 20, height_mm: 20, round_media: true },
	{ id: "round-30", label: "Round 30 mm", width_mm: 30, height_mm: 30, round_media: true },
	{ id: "round-40", label: "Round 40 mm", width_mm: 40, height_mm: 40, round_media: true },
];

export const PRINTER_PROFILES = [
	{
		id: "system", label: "System / exact-size PDF", dpi: 300,
		hint: "300 dpi render; the operating-system driver must print at 100% scale.",
		default_media: "40x30",
		media: [
			...COMMON_MEDIA,
			{ id: "50x30", label: "50 × 30 mm", width_mm: 50, height_mm: 30 },
			{ id: "62x29", label: "62 × 29 mm", width_mm: 62, height_mm: 29 },
			{ id: "62-continuous", label: "62 mm continuous", width_mm: 62, height_mm: 100, continuous_media: true },
		],
	},
	{
		id: "phomemo", label: "Phomemo M110 / M120", dpi: 203,
		hint: "203 dpi, 48 mm print head; Bluetooth density 10 and speed 5 are the print defaults.",
		default_media: "40x30",
		media: [
			{ id: "30x20", label: "30 × 20 mm", width_mm: 30, height_mm: 20 },
			{ id: "30x40", label: "30 × 40 mm", width_mm: 30, height_mm: 40 },
			{ id: "40x30", label: "40 × 30 mm", width_mm: 40, height_mm: 30 },
			{ id: "40x60", label: "40 × 60 mm", width_mm: 40, height_mm: 60 },
			{ id: "round-20", label: "Round 20 mm", width_mm: 20, height_mm: 20, round_media: true },
			{ id: "round-30", label: "Round 30 mm", width_mm: 30, height_mm: 30, round_media: true },
			{ id: "round-40", label: "Round 40 mm", width_mm: 40, height_mm: 40, round_media: true },
		],
	},
	{
		id: "niimbot", label: "NIIMBOT D110 family", dpi: 203,
		hint: "203 dpi, rotated D-series feed; use label stock 12–15 mm across the print head.",
		default_media: "40x15",
		media: [
			{ id: "40x12", label: "40 × 12 mm", width_mm: 40, height_mm: 12 },
			{ id: "30x12", label: "30 × 12 mm", width_mm: 30, height_mm: 12 },
			{ id: "22x12", label: "22 × 12 mm", width_mm: 22, height_mm: 12 },
			{ id: "30x14", label: "30 × 14 mm", width_mm: 30, height_mm: 14 },
			{ id: "40x15", label: "40 × 15 mm", width_mm: 40, height_mm: 15 },
			{ id: "30x15", label: "30 × 15 mm", width_mm: 30, height_mm: 15 },
			{ id: "40x15-continuous", label: "40 × 15 mm continuous", width_mm: 40, height_mm: 15, continuous_media: true },
			{ id: "round-14", label: "Round 14 mm", width_mm: 14, height_mm: 14, round_media: true },
		],
	},
];

export function printerProfileId(target) {
	const normalized = String(target || "").trim().toLowerCase();
	if (["phomemo", "m110", "m110s", "m120"].includes(normalized)) return "phomemo";
	if (["niimbot", "d110", "d-series"].includes(normalized)) return "niimbot";
	if (normalized === "system") return "system";
	return "custom";
}

export function printerProfile(id) {
	return PRINTER_PROFILES.find((item) => item.id === id) || null;
}

export function applyMediaPreset(template, media) {
	return {
		...template,
		width_mm: media.width_mm,
		height_mm: media.height_mm,
		round_media: Boolean(media.round_media),
		continuous_media: Boolean(media.continuous_media),
	};
}

export function applyPrinterProfile(template, id) {
	const profile = printerProfile(id);
	if (!profile) return { ...template, printer_target: "" };
	const media = profile.media.find((item) => item.id === profile.default_media);
	return applyMediaPreset({ ...template, printer_target: profile.id, dpi: profile.dpi }, media);
}

export function matchingMediaId(template, profile) {
	if (!profile) return "";
	return profile.media.find((item) =>
		item.width_mm === Number(template.width_mm)
		&& item.height_mm === Number(template.height_mm)
		&& Boolean(item.round_media) === Boolean(template.round_media)
		&& Boolean(item.continuous_media) === Boolean(template.continuous_media))?.id || "";
}
