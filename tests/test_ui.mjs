import assert from "node:assert/strict";
import fs from "node:fs";
const source = fs.readFileSync(new URL("../web/status.js", import.meta.url), "utf8");
const {statusText, help} = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const waiting = statusText({phase: "processing", frames: null, elapsed: 61, sent_bytes: 100, total_bytes: 100}, "de");
assert.match(waiting.detail, /Warte auf Videoframes/);
assert.match(waiting.detail, /Übertragen: 100%/);
assert.match(waiting.detail, /1:01/);
assert.equal(statusText({phase: 'warming_up', elapsed: 35}, 'de').phase, 'Maxine-Modelle laden');
assert.equal(statusText({phase: 'starting'}, 'en').phase, 'Starting Maxine when needed');
const frames = statusText({phase: "processing", frames: 5, total_frames: 10, width: 3840, height: 2160}, "en");
assert.match(frames.detail, /3840 × 2160/);
assert.match(frames.detail, /5\/10 Frames/);
assert.ok(help.de.some(([name]) => name === "Temporal filtering"));
assert.ok(help.en.some(([name, text]) => name === "Eye size sensitivity" && text.includes("does not enlarge")));

// Exercise the actual extension with a small browser/Comfy host harness.
class Element {
    constructor(tag) {this.tag = tag; this.style = {}; this.children = []; this.attributes = {};}
    append(...items) {this.children.push(...items);}
    setAttribute(key, value) {this.attributes[key] = value;}
    removeAttribute(key) {delete this[key];}
}
const listeners = new Map();
const node = {comfyClass: "MaxineEyeContact", size: [360, 220],
    addDOMWidget(name, type, element, options) {this.element = element; this.options = options; return {};},
    computeSize() {return [410, 420];}, setSize(size) {this.size = size;}};
Object.defineProperty(globalThis, "navigator", {value: {language: "de-DE"}, configurable: true});
globalThis.document = {createElement: (tag) => new Element(tag), createTextNode: (text) => text};
globalThis.__maxineApp = {registerExtension(extension) {this.extension = extension;}, graph: {getNodeById(id) {return id === "2" ? node : null;}}};
globalThis.__maxineApi = {addEventListener(name, callback) {listeners.set(name, callback);}};
globalThis.__maxineStatus = {statusText, help};
const extensionSource = fs.readFileSync(new URL("../web/maxine.js", import.meta.url), "utf8")
    .replace('import { app } from "../../scripts/app.js";', 'const app = globalThis.__maxineApp;')
    .replace('import { api } from "../../scripts/api.js";', 'const api = globalThis.__maxineApi;')
    .replace('import { help, statusText } from "./status.js";', 'const {help, statusText} = globalThis.__maxineStatus;');
await import(`data:text/javascript;base64,${Buffer.from(extensionSource).toString("base64")}`);
__maxineApp.extension.nodeCreated(node);
__maxineApp.extension.setup();
assert.equal(node.options.serialize, false);
listeners.get("maxine_eye_contact.progress")({detail: {node: "2", phase: "processing", indeterminate: true}});
const bar = node.element.children.find((e) => e.tag === "progress");
assert.equal(bar.value, undefined);
listeners.get("maxine_eye_contact.progress")({detail: {node: "2", phase: "complete", fraction: 1}});
assert.equal(bar.value, 1);
assert.equal(node.element.children[0].textContent, "Fertig");
console.log("Frontend status, waiting bar, frame counter and bilingual help passed.");
