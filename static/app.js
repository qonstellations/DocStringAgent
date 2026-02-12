/* ═══════════════════════════════════════════════════════════════════
   Docstring Agent — Frontend Logic
   ═══════════════════════════════════════════════════════════════════ */

(() => {
    "use strict";

    // ── DOM refs ──────────────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const codeInput = $("#code-input");
    const fileInput = $("#file-input");
    const pathInput = $("#path-input");
    const recursiveChk = $("#recursive");
    const overwriteChk = $("#overwrite");
    const modelSelect = $("#model-select");
    const generateBtn = $("#generate-btn");
    const btnContent = $(".btn-content");
    const btnLoader = $(".btn-loader");
    const outputPanel = $("#output-panel");
    const statsEl = $("#stats");
    const copyBtn = $("#copy-btn");
    const downloadBtn = $("#download-btn");
    const uploadZone = $("#upload-zone");
    const uploadFilename = $("#upload-filename");
    const dirResults = $("#dir-results");
    const dirSummary = $("#dir-summary");
    const dirFileList = $("#dir-file-list");
    const toastContainer = $("#toast-container");

    let activeTab = "paste";
    let uploadedFile = null;
    let lastResult = null;
    let activeOutputView = "modified";

    // ── Auto-detect Ollama models on load ─────────────────────────
    (async function loadOllamaModels() {
        try {
            const res = await fetch("/api/ollama-models");
            const data = await res.json();
            const group = document.getElementById("ollama-models");
            if (data.models && data.models.length) {
                data.models.forEach((m, i) => {
                    const opt = document.createElement("option");
                    opt.value = `ollama:${m}`;
                    const short = m.split(":")[0];
                    opt.textContent = `${short} (local)`;
                    group.appendChild(opt);
                    if (i === 0) modelSelect.value = opt.value;
                });
            } else {
                group.hidden = true;
            }
        } catch {
            const group = document.getElementById("ollama-models");
            if (group) group.hidden = true;
        }
    })();

    // ── Input Tab Switching ───────────────────────────────────────
    $$(".input-tabs .tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            const target = tab.dataset.tab;
            if (target === activeTab) return;
            activeTab = target;

            $$(".input-tabs .tab").forEach((t) => {
                t.classList.toggle("active", t.dataset.tab === target);
                t.setAttribute("aria-selected", t.dataset.tab === target);
            });
            $$(".tab-content").forEach((c) => {
                c.classList.toggle("active", c.id === `tab-${target}`);
            });
        });
    });

    // ── Output View Tabs ──────────────────────────────────────────
    $$(".otab").forEach((tab) => {
        tab.addEventListener("click", () => {
            const view = tab.dataset.view;
            if (view === activeOutputView) return;
            activeOutputView = view;

            $$(".otab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
            $$(".output-view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
        });
    });

    // ── File Upload ───────────────────────────────────────────────
    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length) handleFileSelect(e.target.files[0]);
    });

    uploadZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        uploadZone.classList.add("dragover");
    });
    uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("dragover"));
    uploadZone.addEventListener("drop", (e) => {
        e.preventDefault();
        uploadZone.classList.remove("dragover");
        if (e.dataTransfer.files.length) handleFileSelect(e.dataTransfer.files[0]);
    });
    uploadZone.addEventListener("click", (e) => {
        if (e.target === fileInput || e.target.closest(".upload-browse-btn")) return;
    });

    function handleFileSelect(file) {
        if (!file.name.endsWith(".py")) {
            toast("Only .py files are supported", "error");
            return;
        }
        uploadedFile = file;
        uploadFilename.textContent = `📄 ${file.name}`;
        uploadFilename.hidden = false;
        toast(`Selected: ${file.name}`, "info");
    }

    // ── Generate Button ───────────────────────────────────────────
    generateBtn.addEventListener("click", () => {
        if (generateBtn.disabled) return;

        switch (activeTab) {
            case "paste": return handlePaste();
            case "upload": return handleUpload();
            case "path": return handlePath();
        }
    });

    function setLoading(on) {
        generateBtn.disabled = on;
        btnContent.hidden = on;
        btnLoader.hidden = !on;
    }

    // ── Paste handler ─────────────────────────────────────────────
    async function handlePaste() {
        const code = codeInput.value.trim();
        if (!code) return toast("Paste some Python code first", "error");

        setLoading(true);
        try {
            const res = await fetch("/api/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    source_code: code,
                    overwrite: overwriteChk.checked,
                    model: modelSelect.value,
                }),
            });
            if (!res.ok) {
                const err = await res.json();
                if (res.status === 429) {
                    throw new Error("⚠️ RATE LIMIT EXCEEDED: " + (err.detail || "Please try again later."));
                }
                throw new Error(err.detail || "Server error");
            }
            const data = await res.json();
            showSingleResult(data);
        } catch (e) {
            if (e.message.startsWith("⚠️")) {
                showError(e.message);
            } else {
                toast(e.message, "error");
            }
        } finally {
            setLoading(false);
        }
    }

    // ── Upload handler ────────────────────────────────────────────
    async function handleUpload() {
        if (!uploadedFile) return toast("Upload a .py file first", "error");

        setLoading(true);
        try {
            const form = new FormData();
            form.append("file", uploadedFile);
            form.append("overwrite", overwriteChk.checked);
            form.append("model", modelSelect.value);

            const res = await fetch("/api/upload", { method: "POST", body: form });
            if (!res.ok) {
                const err = await res.json();
                if (res.status === 429) {
                    throw new Error("⚠️ RATE LIMIT EXCEEDED: " + (err.detail || "Please try again later."));
                }
                throw new Error(err.detail || "Server error");
            }
            const data = await res.json();
            showSingleResult(data);
        } catch (e) {
            if (e.message.startsWith("⚠️")) {
                showError(e.message);
            } else {
                toast(e.message, "error");
            }
        } finally {
            setLoading(false);
        }
    }

    // ── Path handler ──────────────────────────────────────────────
    async function handlePath() {
        const p = pathInput.value.trim();
        if (!p) return toast("Enter a file or directory path", "error");

        setLoading(true);
        try {
            const res = await fetch("/api/process-path", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    path: p,
                    recursive: recursiveChk.checked,
                    overwrite: overwriteChk.checked,
                    model: modelSelect.value,
                }),
            });
            if (!res.ok) {
                const err = await res.json();
                if (res.status === 429) {
                    throw new Error("⚠️ RATE LIMIT EXCEEDED: " + (err.detail || "Please try again later."));
                }
                throw new Error(err.detail || "Server error");
            }
            const data = await res.json();

            if (data.files.length === 1) {
                showSingleResult({
                    original: data.files[0].original,
                    modified: data.files[0].modified,
                    elements_found: data.files[0].elements_found,
                    docstrings_added: data.files[0].docstrings_added,
                    processing_time: data.processing_time,
                    filename: data.files[0].filepath,
                });
            } else {
                showDirectoryResult(data);
            }
        } catch (e) {
            if (e.message.startsWith("⚠️")) {
                showError(e.message);
            } else {
                toast(e.message, "error");
            }
        } finally {
            setLoading(false);
        }
    }

    // ── Show single-file result ───────────────────────────────────
    function showSingleResult(data) {
        lastResult = data;
        dirResults.hidden = true;

        setCode("code-modified", data.modified);
        setCode("code-original", data.original);
        setCode("code-sbs-original", data.original);
        setCode("code-sbs-modified", data.modified);

        if (data.filename) {
            $("#modified-filename").textContent = data.filename;
        }

        statsEl.innerHTML = `
            <span class="stat">Elements <span class="stat-value">${data.elements_found}</span></span>
            <span class="stat">Added <span class="stat-value success">${data.docstrings_added}</span></span>
            <span class="stat">Time <span class="stat-value">${data.processing_time}s</span></span>
        `;

        const oldBanner = outputPanel.querySelector(".warning-banner");
        if (oldBanner) oldBanner.remove();

        outputPanel.hidden = false;
        $$(".output-view").forEach((v) => v.classList.remove("active"));
        $$(".otab").forEach((t) => t.classList.remove("active"));
        $('[data-view="modified"]').classList.add("active");
        $("#view-modified").classList.add("active");
        activeOutputView = "modified";

        if (data.warnings && data.warnings.length) {
            const banner = document.createElement("div");
            banner.className = "warning-banner";
            banner.innerHTML = `
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                <span class="warning-banner-text">${data.warnings.join("<br>")}</span>
            `;
            const panelHeader = outputPanel.querySelector(".panel-header");
            panelHeader.after(banner);
            toast("Generation failed — see warning below", "error");
        } else {
            toast(`Done! ${data.docstrings_added} docstring(s) generated`, "success");
        }

        outputPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // ── Show Persistent Error ─────────────────────────────────────
    function showError(message) {
        const oldBanner = outputPanel.querySelector(".warning-banner");
        if (oldBanner) oldBanner.remove();

        const banner = document.createElement("div");
        banner.className = "warning-banner";
        banner.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            <span class="warning-banner-text">${message}</span>
            <button class="banner-close-btn" aria-label="Dismiss">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </button>
        `;

        banner.querySelector(".banner-close-btn").addEventListener("click", () => {
            banner.remove();
            outputPanel.hidden = true;
        });

        // Hide other output views/contents to focus on error
        $$(".output-view").forEach(v => v.classList.remove("active"));
        dirResults.hidden = true;

        outputPanel.hidden = false;
        const panelHeader = outputPanel.querySelector(".panel-header");
        panelHeader.after(banner);

        outputPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // ── Show directory result ─────────────────────────────────────
    function showDirectoryResult(data) {
        lastResult = data.files.length ? {
            original: data.files[0].original,
            modified: data.files[0].modified,
        } : null;

        dirResults.hidden = false;

        dirSummary.innerHTML = `
            <span class="stat">Processed <span class="stat-value">${data.total_processed}</span></span>
            <span class="stat">Modified <span class="stat-value success">${data.total_modified}</span></span>
            <span class="stat">Errors <span class="stat-value" style="color: ${data.total_errors ? 'var(--error)' : 'var(--text-muted)'}">${data.total_errors}</span></span>
            <span class="stat">Time <span class="stat-value">${data.processing_time}s</span></span>
        `;

        dirFileList.innerHTML = "";
        data.files.forEach((f) => {
            const item = document.createElement("div");
            item.className = "dir-file-item";
            item.innerHTML = `
                <span class="dir-file-name">${f.filepath}</span>
                <span class="dir-file-badge ${f.changed ? 'changed' : 'unchanged'}">${f.changed ? `+${f.docstrings_added} docstrings` : 'no changes'}</span>
            `;
            item.addEventListener("click", () => {
                showSingleResult({
                    original: f.original,
                    modified: f.modified,
                    elements_found: f.elements_found,
                    docstrings_added: f.docstrings_added,
                    processing_time: data.processing_time,
                    filename: f.filepath,
                });
            });
            dirFileList.appendChild(item);
        });

        statsEl.innerHTML = `
            <span class="stat">Files <span class="stat-value">${data.total_processed}</span></span>
            <span class="stat">Modified <span class="stat-value success">${data.total_modified}</span></span>
            <span class="stat">Time <span class="stat-value">${data.processing_time}s</span></span>
        `;

        outputPanel.hidden = false;

        if (data.files.length) {
            const first = data.files[0];
            setCode("code-modified", first.modified);
            setCode("code-original", first.original);
            setCode("code-sbs-original", first.original);
            setCode("code-sbs-modified", first.modified);
        }

        outputPanel.scrollIntoView({ behavior: "smooth", block: "start" });
        toast(`Done! ${data.total_modified} file(s) modified`, "success");
    }

    // ── Syntax-highlighted code ───────────────────────────────────
    function setCode(elementId, code) {
        const el = document.getElementById(elementId);
        el.textContent = code;
        hljs.highlightElement(el);
    }

    // ── Copy button ───────────────────────────────────────────────
    copyBtn.addEventListener("click", async () => {
        if (!lastResult) return;
        const text = lastResult.modified || "";
        try {
            await navigator.clipboard.writeText(text);
            copyBtn.classList.add("copied");
            copyBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg> Copied!`;
            setTimeout(() => {
                copyBtn.classList.remove("copied");
                copyBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`;
            }, 2000);
        } catch {
            toast("Failed to copy", "error");
        }
    });

    // ── Download button ───────────────────────────────────────────
    downloadBtn.addEventListener("click", () => {
        if (!lastResult) return;
        const text = lastResult.modified || "";
        const name = lastResult.filename || "docstring_output.py";
        const blob = new Blob([text], { type: "text/x-python" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = name.split("/").pop();
        a.click();
        URL.revokeObjectURL(url);
        toast("File downloaded", "success");
    });

    // ── Toast helper ──────────────────────────────────────────────
    function toast(message, type = "info") {
        const el = document.createElement("div");
        el.className = `toast ${type}`;
        el.textContent = message;
        toastContainer.appendChild(el);

        const duration = type === "error" ? 8000 : 4000;
        const dismiss = () => {
            el.classList.add("dismissing");
            setTimeout(() => el.remove(), 300);
        };
        el.addEventListener("click", dismiss);
        setTimeout(dismiss, duration);
    }

    // ── Keyboard shortcut ─────────────────────────────────────────
    document.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            generateBtn.click();
        }
    });

})();
