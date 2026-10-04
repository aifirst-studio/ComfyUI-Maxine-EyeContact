import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { help, statusText } from "./status.js";

const displays = new WeakMap();
const language = navigator.language || "en";

function display(node, data) {
    const ui = displays.get(node);
    if (!ui) return;
    const text = statusText(data, language);
    ui.phase.textContent = text.phase;
    ui.detail.textContent = text.detail;
    if (data.indeterminate) ui.bar.removeAttribute("value");
    else ui.bar.value = data.fraction ?? (data.value || 0) / 1000;
    ui.bar.setAttribute("aria-label", text.phase);
}

app.registerExtension({
    name: "Maxine.EyeContact.Progress",
    nodeCreated(node) {
        if (node.comfyClass !== "MaxineEyeContact") return;
        const de = language.startsWith("de");
        const element = document.createElement("section");
        Object.assign(element.style, {padding: "10px", font: "12px sans-serif", color: "var(--input-text, #ddd)",
            background: "var(--comfy-input-bg, #222)", boxSizing: "border-box", overflow: "auto", borderRadius: "6px"});
        const phase = document.createElement("strong");
        const detail = document.createElement("div");
        const bar = document.createElement("progress");
        bar.max = 1; bar.value = 0; bar.style.width = "100%";
        detail.style.cssText = "min-height:28px;padding-top:5px;line-height:1.4";
        const explanation = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = de ? "Parameter-Hilfe · volle Auflösung" : "Parameter help · original resolution";
        summary.style.cursor = "pointer";
        explanation.append(summary);
        for (const [name, description] of help[de ? "de" : "en"]) {
            const paragraph = document.createElement("p");
            const label = document.createElement("strong");
            label.textContent = `${name}: `;
            paragraph.append(label, document.createTextNode(description));
            explanation.append(paragraph);
        }
        element.append(phase, detail, bar, explanation);
        const widget = node.addDOMWidget("maxine_status", "maxine_status", element, {serialize: false});
        widget.computeSize = () => [node.size[0], 185];
        displays.set(node, {phase, detail, bar});
        display(node, {});
        node.setSize([Math.max(node.size[0], 410), node.computeSize()[1]]);
    },
    setup() {
        api.addEventListener("maxine_eye_contact.progress", ({detail}) => {
            const node = app.graph?.getNodeById(detail.node);
            if (node?.comfyClass === "MaxineEyeContact") display(node, detail);
        });
        api.addEventListener("executing", ({detail}) => {
            const node = app.graph?.getNodeById(detail.node);
            if (node?.comfyClass === "MaxineEyeContact") display(node, {phase: "checking", indeterminate: true});
        });
    },
});
