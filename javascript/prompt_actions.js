(function initSimpleAIPromptActions() {
    if (window.__simpleaiPromptActionsLoaded) return;
    window.__simpleaiPromptActionsLoaded = true;

    let modal = null;
    let toast = null;
    let boundButton = null;
    let pending = false;
    let pendingActionId = "";
    let previousPrompt = "";
    let lastFocused = null;
    let activePromptField = null;
    let pendingPromptField = null;
    let lastAppliedPromptField = null;
    let lastAppliedPreviousPrompt = "";

    function catalogItems() {
        const catalog = window.SimpAIPromptActionCatalog;
        return Array.isArray(catalog?.items) ? catalog.items : [];
    }

    function paramsSource() {
        return window.simpleaiTopbarSystemParams
            || (typeof topbarLastSystemParams !== "undefined" ? topbarLastSystemParams : null)
            || {};
    }

    function currentLang() {
        const params = paramsSource();
        const lang = String(params.__lang || params.state?.__lang || window.locale_lang || "").toLowerCase();
        return lang.startsWith("en") ? "en" : "cn";
    }

    function text(en, cn) {
        return currentLang() === "en" ? (en || cn || "") : (cn || en || "");
    }

    function rootById(id) {
        return typeof getGradioRootById === "function" ? getGradioRootById(id) : document.getElementById(id);
    }

    function fieldById(id) {
        return rootById(id)?.querySelector?.("textarea, input") || null;
    }

    function readField(id) {
        return String(fieldById(id)?.value || "");
    }

    function setField(id, value) {
        if (typeof setGradioTextboxValue === "function" && setGradioTextboxValue(id, value)) return true;
        const field = fieldById(id);
        if (!field) return false;
        field.value = value;
        field.dispatchEvent(new Event("input", { bubbles: true }));
        field.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
    }

    function promptButton() {
        const root = rootById("super_prompter_button");
        if (!root) return null;
        return root.matches?.("button") ? root : root.querySelector?.("button");
    }

    function directorModeEnabled() {
        const root = rootById("scene_director_enabled");
        return !!root?.querySelector?.('input[type="checkbox"]')?.checked;
    }

    function activeDirectorPromptField() {
        if (!directorModeEnabled()) return null;
        const editor = rootById("scene_director_editor_root") || document.querySelector("#scene_director_editor_root");
        return editor?.querySelector?.('.scene-director-shot.is-active-shot [data-scene-director-field="prompt"]')
            || editor?.querySelector?.('[data-scene-director-shot][aria-current="true"] [data-scene-director-field="prompt"]')
            || null;
    }

    function defaultPromptField() {
        return activeDirectorPromptField() || fieldById("positive_prompt");
    }

    function usablePromptField(field) {
        if (!field || !field.isConnected) return null;
        if (field.matches?.('[data-scene-director-field="prompt"]') && !directorModeEnabled()) return null;
        return field;
    }

    function promptField(field = null) {
        return usablePromptField(field) || defaultPromptField();
    }

    function setPromptFieldValue(field, value) {
        const target = usablePromptField(field);
        if (!target) return false;
        if (target === fieldById("positive_prompt")) return setField("positive_prompt", value);
        target.value = String(value ?? "");
        target.dispatchEvent(new Event("input", { bubbles: true }));
        target.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
    }

    function currentPrompt() {
        return String(promptField(activePromptField)?.value || "");
    }

    function isSceneMode() {
        const params = paramsSource();
        if (params && typeof params === "object" && Object.prototype.hasOwnProperty.call(params, "__is_scene_frontend")) {
            return !!params.__is_scene_frontend;
        }
        if (document.documentElement?.classList?.contains("simpai-scene-frontend")) return true;
        const panel = rootById("scene_panel");
        if (!panel) return false;
        const style = window.getComputedStyle(panel);
        return style.display !== "none" && style.visibility !== "hidden" && panel.offsetParent !== null;
    }

    function isVlmEnabled() {
        if (typeof getGradioCheckboxById === "function") {
            const input = getGradioCheckboxById("vlm_checkbox");
            if (input) return !!input.checked;
        }
        const root = rootById("vlm_checkbox");
        const input = root?.querySelector?.('input[type="checkbox"]');
        return input ? !!input.checked : true;
    }

    function isGenerationActive() {
        const visible = (id) => {
            const root = rootById(id);
            if (!root) return false;
            if (typeof elementIsVisible === "function") return elementIsVisible(root);
            return root.offsetParent !== null;
        };
        return visible("skip_button") || visible("stop_button");
    }

    function mainVideoAvailable() {
        if (readField("scene_video_first_frame_path").trim()) return true;
        const root = rootById("scene_video");
        const video = root?.querySelector?.("video");
        return !!(video && String(video.currentSrc || video.src || "").trim());
    }

    function currentSceneFrontend(params = paramsSource()) {
        const prepared = params?.__preset_prepared;
        const candidates = [
            params?.scene_frontend,
            prepared?.engine?.scene_frontend,
            prepared?.default_engine?.scene_frontend,
            params?.default_engine?.scene_frontend,
        ];
        return candidates.find((value) => value && typeof value === "object") || {};
    }

    function sceneList(value) {
        const items = Array.isArray(value) ? value : String(value || "").split(",");
        return new Set(items.map((item) => String(item || "").trim()).filter(Boolean));
    }

    function presetAcceptsMainVideo() {
        if (!isSceneMode()) return false;
        const params = paramsSource();
        const sceneFrontend = currentSceneFrontend(params);
        const hasResolvedHidden = Object.prototype.hasOwnProperty.call(params, "__scene_disvisible");
        const hidden = sceneList(hasResolvedHidden ? params.__scene_disvisible : sceneFrontend.disvisible);
        if (hidden.has("scene_video")) return false;

        const theme = String(params.__scene_theme || params.scene_theme || "").trim();
        const rawCapability = sceneFrontend.director_capability;
        const capability = rawCapability && typeof rawCapability === "object" && !Object.prototype.hasOwnProperty.call(rawCapability, "video_policy")
            ? rawCapability[theme]
            : rawCapability;
        return String(capability?.video_policy || "").trim().toLowerCase() !== "forbidden";
    }

    function mainVideoContextAvailable() {
        return presetAcceptsMainVideo() && mainVideoAvailable();
    }

    function currentContextText() {
        const params = paramsSource();
        const preset = String(params.__preset || params.preset || "").trim();
        const theme = String(params.__scene_theme || params.scene_theme || "").trim();
        const mode = isSceneMode() ? text("Scene mode", "场景模式") : text("Classic mode", "经典模式");
        return [mode, preset, theme].filter(Boolean).join(" · ");
    }

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        })[ch]);
    }

    function actionLabel(item) {
        return currentLang() === "en" ? (item.label_en || item.label_cn || item.id) : (item.label_cn || item.label_en || item.id);
    }

    function actionDescription(item) {
        return currentLang() === "en"
            ? (item.description_en || item.description_cn || "")
            : (item.description_cn || item.description_en || "");
    }

    function actionAvailability(item) {
        const mode = isSceneMode() ? "scene" : "classic";
        if (Array.isArray(item.modes) && !item.modes.includes(mode)) {
            return { enabled: false, reason: text("Unavailable in this mode", "当前模式不可用") };
        }
        if ((item.requires_vlm || (mode === "scene" && item.requires_vlm_scene)) && !isVlmEnabled()) {
            return { enabled: false, reason: text("Enable VLM first", "需要启用 VLM") };
        }
        return { enabled: !pending, reason: "" };
    }

    function ensureModal() {
        if (modal && document.body.contains(modal)) return modal;
        modal = document.createElement("div");
        modal.className = "simpleai-prompt-action-modal";
        modal.setAttribute("aria-hidden", "true");
        modal.innerHTML = `
            <div class="simpleai-prompt-action-backdrop" data-prompt-action="close"></div>
            <section class="simpleai-prompt-action-panel" role="dialog" aria-modal="true" aria-labelledby="simpleai-prompt-action-title">
                <header class="simpleai-prompt-action-header">
                    <div>
                        <h2 id="simpleai-prompt-action-title" data-role="title"></h2>
                        <p data-role="context"></p>
                    </div>
                    <button type="button" class="simpleai-prompt-action-icon-button" data-prompt-action="close" aria-label="Close">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </header>
                <label class="simpleai-prompt-action-video-option" data-role="video-option">
                    <span>
                        <i class="fa-solid fa-film"></i>
                        <span data-role="video-label"></span>
                    </span>
                    <input type="checkbox" data-role="use-video" checked>
                </label>
                <div class="simpleai-prompt-action-list" data-role="list"></div>
                <div class="simpleai-prompt-action-status" data-role="status" aria-live="polite"></div>
            </section>`;
        modal.addEventListener("click", (event) => {
            const control = event.target?.closest?.("[data-prompt-action]");
            const action = control?.getAttribute?.("data-prompt-action");
            if (action === "close") {
                closeModal();
                return;
            }
            if (action === "run") {
                const actionId = control.getAttribute("data-action-id") || "";
                runAction(actionId);
            }
        });
        document.body.appendChild(modal);
        return modal;
    }

    function setStatus(message, kind) {
        const node = ensureModal().querySelector('[data-role="status"]');
        if (!node) return;
        node.textContent = String(message || "");
        node.classList.toggle("is-error", kind === "error");
        node.classList.toggle("is-busy", kind === "busy");
    }

    function renderModal() {
        const node = ensureModal();
        node.querySelector('[data-role="title"]').textContent = text("Prompt Tools", "提示工具");
        node.querySelector('[data-role="context"]').textContent = currentContextText();
        const hasVideo = mainVideoContextAvailable();
        const videoOption = node.querySelector('[data-role="video-option"]');
        videoOption.hidden = !hasVideo;
        node.querySelector('[data-role="use-video"]').disabled = !hasVideo;
        node.querySelector('[data-role="video-label"]').textContent = text(
            "Use the main video for visual expansion (up to 8 frames)",
            "扩写时读取主要传入视频（最多 8 帧）",
        );

        const mode = isSceneMode() ? "scene" : "classic";
        const items = catalogItems().filter((item) => !Array.isArray(item.modes) || item.modes.includes(mode));
        const list = node.querySelector('[data-role="list"]');
        if (!items.length) {
            list.innerHTML = `<div class="simpleai-prompt-action-empty">${escapeHtml(text("No prompt actions are registered.", "没有可用的提示词能力。"))}</div>`;
            return;
        }
        list.innerHTML = items.map((item) => {
            const availability = actionAvailability(item);
            const badges = [];
            if (item.id === "smart_expand" && mode === "scene") badges.push(text("Scene agent", "场景智能体"));
            if (hasVideo && item.media_policy === "main_video_auto") badges.push(text("Video", "视频"));
            if (item.requires_vlm || (mode === "scene" && item.requires_vlm_scene)) badges.push("VLM");
            const busy = pending && pendingActionId === item.id;
            const stateText = busy ? text("Working...", "处理中…") : availability.reason;
            return `
                <button type="button"
                        class="simpleai-prompt-action-item${item.featured ? " is-featured" : ""}${busy ? " is-busy" : ""}"
                        data-prompt-action="run"
                        data-action-id="${escapeHtml(item.id)}"
                        ${availability.enabled ? "" : "disabled"}>
                    <span class="simpleai-prompt-action-item-icon"><i class="fa-solid ${escapeHtml(item.icon || "fa-wand-magic-sparkles")}"></i></span>
                    <span class="simpleai-prompt-action-item-main">
                        <span class="simpleai-prompt-action-item-title">${escapeHtml(actionLabel(item))}</span>
                        <span class="simpleai-prompt-action-item-description">${escapeHtml(actionDescription(item))}</span>
                        ${badges.length ? `<span class="simpleai-prompt-action-item-badges">${badges.map((badge) => `<span>${escapeHtml(badge)}</span>`).join("")}</span>` : ""}
                        ${stateText ? `<span class="simpleai-prompt-action-item-state">${escapeHtml(stateText)}</span>` : ""}
                    </span>
                    <span class="simpleai-prompt-action-item-arrow"><i class="fa-solid ${busy ? "fa-spinner fa-spin" : "fa-chevron-right"}"></i></span>
                </button>`;
        }).join("");
    }

    function openModal(field = null) {
        activePromptField = promptField(field);
        if (!currentPrompt().trim() || isGenerationActive()) return;
        lastFocused = document.activeElement;
        renderModal();
        setStatus("", "");
        const node = ensureModal();
        node.classList.add("is-open");
        node.removeAttribute("aria-hidden");
        requestAnimationFrame(() => node.querySelector('[data-prompt-action="close"]')?.focus?.());
    }

    function closeModal() {
        if (!modal) return;
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        if (lastFocused?.focus) requestAnimationFrame(() => lastFocused.focus());
    }

    function hiddenTriggerButton() {
        const root = rootById("prompt_action_trigger");
        if (!root) return null;
        return root.matches?.("button") ? root : root.querySelector?.("button");
    }

    function runAction(actionId) {
        if (pending) return;
        const item = catalogItems().find((candidate) => candidate.id === actionId);
        if (!item) return;
        const availability = actionAvailability(item);
        if (!availability.enabled) {
            setStatus(availability.reason, "error");
            return;
        }
        const trigger = hiddenTriggerButton();
        if (!trigger) {
            setStatus(text("Prompt action bridge is unavailable.", "提示工具执行组件不可用。"), "error");
            return;
        }

        pendingPromptField = promptField(activePromptField);
        previousPrompt = String(pendingPromptField?.value || "");
        const useVideoInput = ensureModal().querySelector('[data-role="use-video"]');
        const options = {
            use_video: item.media_policy === "main_video_auto" && mainVideoContextAvailable()
                ? !!useVideoInput?.checked
                : false,
            language: currentLang(),
            direction: "auto",
        };
        if (!setField("prompt_action_input", previousPrompt)
                || !setField("prompt_action_id", actionId)
                || !setField("prompt_action_options", JSON.stringify(options))) {
            pendingPromptField = null;
            setStatus(text("Prompt action parameters could not be prepared.", "提示工具参数写入失败。"), "error");
            return;
        }

        pending = true;
        pendingActionId = actionId;
        setStatus(text("Processing the prompt...", "正在处理提示词…"), "busy");
        renderModal();
        trigger.click();
    }

    function ensureToast() {
        if (toast && document.body.contains(toast)) return toast;
        toast = document.createElement("div");
        toast.className = "simpleai-prompt-action-toast";
        toast.innerHTML = `
            <span data-role="message"></span>
            <button type="button" data-role="undo"></button>`;
        toast.querySelector('[data-role="undo"]').addEventListener("click", () => {
            if (setPromptFieldValue(lastAppliedPromptField, lastAppliedPreviousPrompt)) {
                toast.classList.remove("is-open");
                if (typeof syncPositivePromptMetaState === "function") {
                    try { syncPositivePromptMetaState(); } catch (error) {}
                }
            }
        });
        document.body.appendChild(toast);
        return toast;
    }

    function showSuccessToast(result) {
        const node = ensureToast();
        const frames = Number(result?.media?.sampled_frames || 0);
        node.querySelector('[data-role="message"]').textContent = frames > 0
            ? text(`Prompt updated · read ${frames} video frames`, `提示词已更新 · 已读取 ${frames} 帧视频`)
            : text("Prompt updated", "提示词已更新");
        node.querySelector('[data-role="undo"]').textContent = text("Undo", "撤销");
        node.classList.add("is-open");
        window.clearTimeout(node.__simpleaiHideTimer);
        node.__simpleaiHideTimer = window.setTimeout(() => node.classList.remove("is-open"), 7000);
    }

    function parseResult(value) {
        if (value && typeof value === "object") return value;
        try {
            const parsed = JSON.parse(String(value || "{}"));
            return parsed && typeof parsed === "object" ? parsed : {};
        } catch (error) {
            return {};
        }
    }

    window.completeSimpleAIPromptAction = function completeSimpleAIPromptAction(value) {
        const result = parseResult(value);
        const target = pendingPromptField;
        pending = false;
        pendingActionId = "";
        if (result.ok) {
            if (!setPromptFieldValue(target, String(result.text ?? previousPrompt))) {
                pendingPromptField = null;
                renderModal();
                setStatus(text("The target prompt is no longer available.", "目标提示词已不可用。"), "error");
                return;
            }
            lastAppliedPromptField = target;
            lastAppliedPreviousPrompt = previousPrompt;
            pendingPromptField = null;
            closeModal();
            showSuccessToast(result);
            if (typeof syncPositivePromptMetaState === "function") {
                try { syncPositivePromptMetaState(); } catch (error) {}
            }
            return;
        }
        pendingPromptField = null;
        renderModal();
        setStatus(result.error || text("Prompt action failed.", "提示词处理失败。"), "error");
    };

    function setButtonLabel() {
        const button = promptButton();
        if (!button) return;
        const label = text("Prompt Tools", "提示工具");
        const title = text("Open prompt tools", "打开提示工具");
        if (button.textContent !== label) button.textContent = label;
        if (button.getAttribute("title") !== title) button.setAttribute("title", title);
        if (button.getAttribute("aria-label") !== label) button.setAttribute("aria-label", label);
    }

    function onButtonClick(event) {
        const button = promptButton();
        if (!button || (event.target !== button && !button.contains(event.target))) return;
        event.preventDefault();
        event.stopPropagation();
        if (button.disabled || button.getAttribute("aria-disabled") === "true") return;
        openModal(defaultPromptField());
    }

    function bindButton() {
        const button = promptButton();
        setButtonLabel();
        if (!button || boundButton === button) return;
        if (boundButton) boundButton.removeEventListener("click", onButtonClick, true);
        button.addEventListener("click", onButtonClick, true);
        boundButton = button;
    }

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && modal?.classList.contains("is-open")) closeModal();
    });

    window.refreshSimpleAIPromptToolsButton = bindButton;
    window.openSimpleAIPromptToolsForField = function openSimpleAIPromptToolsForField(field) {
        openModal(field);
    };
    window.simpleAIPromptToolsHasText = function simpleAIPromptToolsHasText() {
        return !!String(defaultPromptField()?.value || "").trim();
    };
    if (typeof onUiLoaded === "function") onUiLoaded(bindButton);
    if (typeof onAfterUiUpdate === "function") onAfterUiUpdate(bindButton);
})();
