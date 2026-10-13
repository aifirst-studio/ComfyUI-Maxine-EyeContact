const phases = {
    en: {starting: "Starting Maxine when needed", warming_up: "Waiting for Maxine models", checking: "Checking service", exporting: "Exporting input", reading: "Reading input",
        preparing: "Preparing original resolution", processing: "Correcting eye contact",
        validating: "Checking corrected frames", audio: "Restoring source audio",
        final_check: "Checking final video", iris_color: "Matching source iris colour", complete: "Complete", error: "Stopped / error"},
    de: {starting: "Maxine bei Bedarf starten", warming_up: "Maxine-Modelle laden", checking: "Dienst prüfen", exporting: "Eingang exportieren", reading: "Eingang lesen",
        preparing: "Originalauflösung vorbereiten", processing: "Blickkontakt korrigieren",
        validating: "Korrigierte Frames prüfen", audio: "Originalton hinzufügen",
        final_check: "Ergebnis prüfen", iris_color: "Original-Irisfarbe angleichen", complete: "Fertig", error: "Abgebrochen / Fehler"},
};

export function statusText(data, language = "en") {
    const de = language.startsWith("de");
    const labels = phases[de ? "de" : "en"];
    const phase = labels[data.phase] || (de ? "Bereit zum Ausführen" : "Ready to run");
    const extra = [];
    if (data.width && data.height) extra.push(`${data.width} × ${data.height}`);
    if (data.phase === "processing") {
        if (data.frames != null && data.total_frames) {
            extra.push(`${data.frames}/${data.total_frames} Frames`);
        } else {
            extra.push(de ? "Warte auf Videoframes / Modellstart" : "Waiting for video frames / model warm-up");
        }
        if (data.total_bytes) {
            const percent = Math.min(100, Math.round(100 * data.sent_bytes / data.total_bytes));
            extra.push(`${de ? "Übertragen" : "Uploaded"}: ${percent}%`);
        }
        if (data.received_bytes) extra.push(`${(data.received_bytes / 1048576).toFixed(1)} MiB ${de ? "empfangen" : "received"}`);
    } else if (data.fraction != null) extra.push(`${Math.round(data.fraction * 100)}%`);
    if (data.matched_frames != null && ["iris_color", "complete"].includes(data.phase)) {
        extra.push(`${data.matched_frames} ${de ? "Frames mit Farbabgleich" : "colour-matched frames"}`);
    }
    if (data.elapsed != null) extra.push(`${Math.floor(data.elapsed / 60)}:${String(data.elapsed % 60).padStart(2, "0")}`);
    return {phase, detail: extra.join(" · ")};
}

export const help = {
    en: [
        ["Resolution", "Always the input's original resolution; no downscaling. Set Save Video to format auto / codec auto to keep the corrected stream."],
        ["Eye size sensitivity", "2–6 controls the eye-area blending region: 2 smaller, 6 larger. Start with 3. It does not enlarge eyes or set correction strength. Compare blend edges in a short clip."],
        ["Detect closed eyes", "On respects blinking, closed eyes and occlusion. Recommended for eye-contact correction; it does not open closed eyes."],
        ["Temporal filtering", "On smooths eye-contact landmarks across frames to reduce jitter/flicker. Uses NVIDIA's default 0xffffffff; off sends 0. Recommended on for recorded video."],
        ["Preserve iris colour", "Experimental CPU colour matching from the source iris to redirected eyes. Retains gaze; skips uncertain/closed eyes. Adds a player-compatible H.264 High/YUV420 encode at CRF 1, at the original resolution. Very high quality, not mathematically lossless. Inspect a short clip; exact colour/identity is not guaranteed."],
        ["Natural lookaway", "Adds occasional small gaze changes, up to 5°, to soften a fixed stare. Off keeps continuous correction within NVIDIA's supported pose range."],
        ["Lossless output", "On encodes NIM's corrected frames without additional output compression. Iris-colour matching adds a CRF 1 encode, so its final output is not mathematically lossless. Input conversion still requires 8-bit SDR YUV420 H.264."],
        ["Input quality", "Maximum (CRF 1) is the default. Only used when conversion is needed. Compatible H.264 sources are copied directly. CRF 1 is very high quality, but not mathematically lossless."],
        ["Lossy bitrate", "Only applies when lossless output is off. Mbit/s; higher values retain more detail and increase file size."],
        ["Progress", "Frame counts refer to complete encoded output frames received from NIM. If MP4 metadata cannot be counted, the bar waits without inventing an inference percentage. Stage progress is not an ETA."],
    ],
    de: [
        ["Auflösung", "Immer die Originalauflösung des Eingangs, ohne Verkleinerung. Save Video auf Format auto / Codec auto stellen, um den korrigierten Stream zu erhalten."],
        ["Eye size sensitivity", "2–6 bestimmt den Überblendbereich um die Augen: 2 kleiner, 6 größer. Mit 3 anfangen. Vergrößert weder Augen noch Korrekturstärke. Übergänge an einem kurzen Clip vergleichen."],
        ["Detect closed eyes", "An berücksichtigt Blinzeln, geschlossene oder verdeckte Augen. Für die Blickkorrektur empfohlen; öffnet keine geschlossenen Augen."],
        ["Temporal filtering", "An glättet die berechneten Augen-Landmarks über mehrere Frames gegen Zittern/Flackern. NVIDIAs Standard 0xffffffff, ausgeschaltet 0. Für Videos eingeschaltet lassen."],
        ["Preserve iris colour", "Experimenteller CPU-Farbabgleich der erkannten Iris mit dem Original. Blickrichtung bleibt erhalten, unsichere/geschlossene Augen werden ausgelassen. Zusätzliche playerkompatible H.264-High/YUV420-Kodierung bei CRF 1 und Originalauflösung: sehr hochwertig, nicht mathematisch verlustfrei. Kurzen Clip vergleichen; exakte Farbe/Identität nicht garantiert."],
        ["Natural lookaway", "Fügt gelegentlich kleine Blickbewegungen bis 5° ein, damit der Blick weniger starr wirkt. Aus hält die Korrektur innerhalb von NVIDIAs Kopf-/Blickwinkelbereich kontinuierlich aktiv."],
        ["Lossless output", "An speichert NIMs korrigierte Frames ohne zusätzliche verlustbehaftete Ausgabekompression. Der Iris-Farbabgleich kodiert anschließend bei CRF 1; dessen Endausgabe ist nicht mathematisch verlustfrei. Eingangskonvertierung bleibt auf 8-Bit-SDR-YUV420-H.264 begrenzt."],
        ["Input quality", "Maximum (CRF 1) ist Standard und greift nur bei nötiger Konvertierung. Kompatibles H.264 wird direkt kopiert. CRF 1 ist sehr hochwertig, aber nicht mathematisch verlustfrei."],
        ["Lossy bitrate", "Gilt nur bei ausgeschaltetem Lossless output. Mbit/s; höhere Werte erhalten mehr Details und erzeugen größere Dateien."],
        ["Fortschritt", "Gezählt werden vollständig empfangene, kodierte Ausgabe-Frames. Bei ungeeigneten MP4-Metadaten zeigt die Node eine Warteanzeige ohne erfundene Inferenz-Prozentzahl. Die Schritte sind keine Restzeitprognose."],
    ],
};
