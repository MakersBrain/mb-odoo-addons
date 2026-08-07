/** @odoo-module **/

const ADAPTER_KEY = "mb_label.last_printer_adapter";
const DEVICE_KEY_PREFIX = "mb_label.last_ble_device.";

function availableStorage(storage) {
	return storage || globalThis.localStorage;
}

export function rememberedAdapter(storage) {
	try {
		return availableStorage(storage).getItem(ADAPTER_KEY) || "";
	} catch {
		return "";
	}
}

export function rememberAdapter(adapterId, storage) {
	try {
		availableStorage(storage).setItem(ADAPTER_KEY, adapterId);
	} catch {
		// Printing must remain usable when storage is blocked by browser policy.
	}
}

export function forgetBluetoothDevice(adapterId, storage) {
	try {
		availableStorage(storage).removeItem(`${DEVICE_KEY_PREFIX}${adapterId}`);
	} catch {
		// A blocked storage backend is equivalent to having no remembered device.
	}
}

export async function selectBluetoothDevice(adapterId, requestOptions, {
	bluetooth = globalThis.navigator?.bluetooth,
	storage,
	forceChooser = false,
} = {}) {
	if (!bluetooth) throw new Error("Web Bluetooth is unavailable in this browser.");
	const key = `${DEVICE_KEY_PREFIX}${adapterId}`;
	if (!forceChooser && typeof bluetooth.getDevices === "function") {
		try {
			const rememberedId = availableStorage(storage).getItem(key);
			if (rememberedId) {
				const granted = await bluetooth.getDevices();
				const remembered = granted.find((device) => device.id === rememberedId);
				if (remembered) return remembered;
			}
		} catch {
			// Fall through to Chrome's chooser if permission or storage was reset.
		}
	}
	const device = await bluetooth.requestDevice(requestOptions);
	try {
		availableStorage(storage).setItem(key, device.id);
	} catch {
		// The current print can continue even if the choice cannot be persisted.
	}
	return device;
}
