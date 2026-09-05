/** @odoo-module **/

import { beforeEach, destroy, expect, test } from "@odoo/hoot";
import {
    allowTranslations,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { localization } from "@web/core/l10n/localization";
import { LabelEditor } from "@mb_label/editor/label_editor";
import { EventBus } from "@odoo/owl";

const templates = [
    {
        id: 1,
        name: "First label",
        version_number: 1,
        width_mm: 40,
        height_mm: 30,
        dpi: 203,
        document: {
            schema: 1,
            elements: [
                { id: "name", type: "text", x: 2, y: 2, width: 20, height: 5, text: "Cup" },
            ],
        },
    },
    {
        id: 2,
        name: "Second label",
        version_number: 1,
        width_mm: 50,
        height_mm: 25,
        dpi: 203,
        document: { schema: 1, elements: [] },
    },
];

function editorEnvironment(dialogAdd = () => () => {}) {
    return {
        bus: new EventBus(),
        services: {
            dialog: { add: dialogAdd },
            notification: { add() {} },
            orm: {
                call(_model, method) {
                    if (method === "editor_preview_options") return { products: [], lots: [] };
                    if (method === "editor_bootstrap") return templates;
                    throw new Error(`Unexpected method ${method}`);
                },
            },
        },
    };
}

async function mountEditor(dialogAdd) {
    return mountWithCleanup(LabelEditor, {
        env: editorEnvironment(dialogAdd),
        props: { action: {} },
    });
}

function pointerEventTarget() {
    const canvas = { getBoundingClientRect: () => ({ width: 400 }) };
    return {
        parentElement: canvas,
        closest: () => canvas,
    };
}

function beginPointerInteraction(editor, resize = false) {
    const event = {
        button: 0,
        clientX: 10,
        clientY: 10,
        currentTarget: pointerEventTarget(),
        preventDefault() {},
        stopPropagation() {},
    };
    if (resize) editor.beginResize(event, "name");
    else editor.beginDrag(event, "name");
}

function trackBrowserListeners() {
    const active = new Map();
    patchWithCleanup(browser, {
        addEventListener(type, handler) {
            if (!active.has(type)) active.set(type, new Set());
            active.get(type).add(handler);
        },
        removeEventListener(type, handler) {
            active.get(type)?.delete(handler);
        },
    });
    return active;
}

function editorListenerCount(active, editor) {
    return editor.pointerListeners.reduce(
        (count, [type, handler]) => count + Number(active.get(type)?.has(handler)),
        0,
    );
}

beforeEach(() => {
    allowTranslations();
    patchWithCleanup(localization, { direction: "ltr" });
});

test("drag and resize listeners are removed on every terminal event", async () => {
    const active = trackBrowserListeners();
    const editor = await mountEditor();

    for (const [resize, terminalEvent] of [
        [false, "pointerup"],
        [true, "pointercancel"],
        [false, "blur"],
    ]) {
        beginPointerInteraction(editor, resize);
        expect(editorListenerCount(active, editor)).toBe(4);
        const terminalHandler = editor.pointerListeners.find(([type]) => type === terminalEvent)[1];
        terminalHandler();
        expect(editorListenerCount(active, editor)).toBe(0);
        expect(editor.drag).toBe(null);
    }
});

test("unmount during drag removes listeners and prevents stale pointer updates", async () => {
    const active = trackBrowserListeners();
    const editor = await mountEditor();
    beginPointerInteraction(editor);
    const staleMove = editor.onPointerMove;

    destroy(editor);

    expect(editorListenerCount(active, editor)).toBe(0);
    expect(editor.drag).toBe(null);
    expect(() => staleMove({ clientX: 20, clientY: 20 })).not.toThrow();
});

test("repeated editor mounts do not retain pointer listeners", async () => {
    const active = trackBrowserListeners();

    for (let cycle = 0; cycle < 3; cycle++) {
        const editor = await mountEditor();
        beginPointerInteraction(editor, cycle % 2 === 1);
        expect(editorListenerCount(active, editor)).toBe(4);
        destroy(editor);
        expect(editorListenerCount(active, editor)).toBe(0);
    }
});

test("dirty template selection uses the confirmation dialog", async () => {
    let dialogComponent;
    let dialogProps;
    let dialogOptions;
    const editor = await mountEditor((component, props, options) => {
        dialogComponent = component;
        dialogProps = props;
        dialogOptions = options;
        return () => options.onClose();
    });
    editor.state.dirty = true;

    expect(editor.selectTemplate(2)).toBe(false);
    expect(dialogComponent).toBe(ConfirmationDialog);
    expect(dialogProps.body).toBe("Discard unsaved label changes?");
    expect(editor.state.selectedTemplateId).toBe(1);

    dialogProps.confirm();
    dialogOptions.onClose();
    expect(editor.state.selectedTemplateId).toBe(2);
    expect(editor.state.dirty).toBe(false);
});

test("cancelling or dismissing template confirmation preserves the edit", async () => {
    let dialogProps;
    let dialogOptions;
    const editor = await mountEditor((_component, props, options) => {
        dialogProps = props;
        dialogOptions = options;
        return () => options.onClose();
    });
    editor.state.dirty = true;
    let restores = 0;

    editor.selectTemplate(2, () => restores++);
    dialogProps.cancel();
    dialogOptions.onClose();
    expect(editor.state.selectedTemplateId).toBe(1);
    expect(editor.state.dirty).toBe(true);
    expect(restores).toBeGreaterThan(0);

    editor.selectTemplate(2, () => restores++);
    dialogProps.dismiss();
    dialogOptions.onClose();
    expect(editor.state.selectedTemplateId).toBe(1);
    expect(editor.state.dirty).toBe(true);
});
