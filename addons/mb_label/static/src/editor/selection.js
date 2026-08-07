/** @odoo-module **/

export function shouldClearWorkspaceSelection(event) {
	if (!event) return true;
	return !event.target?.closest?.(".o_mb_label_element");
}
