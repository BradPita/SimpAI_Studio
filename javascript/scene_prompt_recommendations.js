(function initScenePromptRecommendations() {
    if (window.__simpleaiScenePromptRecommendationsLoaded) return;
    window.__simpleaiScenePromptRecommendationsLoaded = true;

    const TARGET_LABELS = {
        positive_prompt: ["Prompt", "主提示词"],
        scene_additional_prompt: ["Additional", "附加提示词"],
        scene_additional_prompt_2: ["Additional 2", "附加提示词 2"],
    };

    let modal = null;
    let activeItems = [];
    let clickBoundButton = null;
    let randomPromptPending = false;
    let recentRandomHistory = [];
    const RANDOM_HISTORY_LIMIT = 10;
    const RANDOM_HISTORY_TAG_LIMIT = 80;

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

    function isSceneMode() {
        const params = paramsSource();
        if (params && typeof params === "object" && Object.prototype.hasOwnProperty.call(params, "__is_scene_frontend")) {
            return !!params.__is_scene_frontend;
        }
        if (document.documentElement?.classList?.contains("simpai-scene-frontend")) return true;
        const panel = typeof getGradioRootById === "function" ? getGradioRootById("scene_panel") : document.getElementById("scene_panel");
        if (!panel) return false;
        const style = window.getComputedStyle(panel);
        return style.display !== "none" && style.visibility !== "hidden" && panel.offsetParent !== null;
    }

    function selectedSceneTheme() {
        const params = paramsSource();
        const direct = String(params.__scene_theme || params.scene_theme || "").trim();
        if (direct) return direct;
        const root = typeof getGradioRootById === "function" ? getGradioRootById("scene_theme") : document.getElementById("scene_theme");
        const checked = root?.querySelector?.('input[type="radio"]:checked');
        if (checked?.value) return checked.value;
        const input = root?.querySelector?.("input, textarea");
        return String(input?.value || "").trim();
    }

    function currentPreset() {
        const params = paramsSource();
        return String(params.__preset || params.preset || "").trim();
    }

    function promptButton() {
        const root = typeof getGradioRootById === "function" ? getGradioRootById("random_prompt_button") : document.getElementById("random_prompt_button");
        if (!root) return null;
        return root.matches?.("button") ? root : root.querySelector?.("button");
    }

    function setPromptButtonLabel() {
        const button = promptButton();
        if (!button) return;
        const label = isSceneMode() ? text("Prompt Picks", "推荐提示词") : text("Random Prompt", "随机提示词");
        if (button.textContent !== label) button.textContent = label;
        if (button.getAttribute("title") !== label) button.setAttribute("title", label);
        if (button.getAttribute("aria-label") !== label) button.setAttribute("aria-label", label);
    }

    async function postJson(url, payload) {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload || {}),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false) {
            throw new Error(data.details || data.error || response.statusText || "Request failed");
        }
        return data;
    }

    function ensureModal() {
        if (modal && document.body.contains(modal)) return modal;
        modal = document.createElement("div");
        modal.className = "simpleai-prompt-recommendation-modal";
        modal.innerHTML = `
            <div class="simpleai-prompt-recommendation-backdrop" data-action="close"></div>
            <section class="simpleai-prompt-recommendation-panel" role="dialog" aria-modal="true">
                <header class="simpleai-prompt-recommendation-header">
                    <div>
                        <h2 data-role="title"></h2>
                        <p data-role="subtitle"></p>
                    </div>
                    <button type="button" class="simpleai-prompt-recommendation-icon-button" data-action="close" aria-label="Close">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </header>
                <div class="simpleai-prompt-recommendation-list" data-role="list"></div>
            </section>`;
        modal.addEventListener("click", (evt) => {
            const action = evt.target?.closest?.("[data-action]")?.getAttribute("data-action");
            if (action === "close") {
                closeModal();
                return;
            }
            if (action === "apply") {
                const itemEl = evt.target.closest("[data-item-index]");
                const item = activeItems[Number(itemEl?.getAttribute("data-item-index"))];
                if (item) applyPromptItem(item);
            }
        });
        document.body.appendChild(modal);
        return modal;
    }

    function closeModal() {
        if (!modal) return;
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
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

    function targetLabel(target) {
        const pair = TARGET_LABELS[target] || TARGET_LABELS.positive_prompt;
        return text(pair[0], pair[1]);
    }

    function renderItems(items, preset, sceneTheme) {
        const node = ensureModal();
        activeItems = Array.isArray(items) ? items : [];
        node.querySelector('[data-role="title"]').textContent = text("Prompt Picks", "推荐提示词");
        const sub = [preset, sceneTheme].filter(Boolean).join(" / ");
        node.querySelector('[data-role="subtitle"]').textContent = sub || text("Local prompt files", "本地提示词文件");
        const list = node.querySelector('[data-role="list"]');
        if (!activeItems.length) {
            list.innerHTML = `<div class="simpleai-prompt-recommendation-empty">${escapeHtml(text("No prompt file matched this preset.", "当前 preset 还没有推荐提示词文件。"))}</div>`;
            return;
        }
        list.innerHTML = activeItems.map((item, index) => `
            <article class="simpleai-prompt-recommendation-item" data-item-index="${index}">
                <div class="simpleai-prompt-recommendation-item-main">
                    <div class="simpleai-prompt-recommendation-item-title">${escapeHtml(item.title || item.title_cn || item.title_en || item.id || "")}</div>
                    <div class="simpleai-prompt-recommendation-item-prompt">${escapeHtml(item.prompt || "")}</div>
                    <div class="simpleai-prompt-recommendation-item-meta">
                        <span>${escapeHtml(targetLabel(item.target))}</span>
                        ${(item.seed_terms || []).slice(0, 4).map((term) => `<span>${escapeHtml(term)}</span>`).join("")}
                    </div>
                </div>
                <button type="button" data-action="apply" class="simpleai-prompt-recommendation-apply">
                    <i class="fa-solid fa-plus"></i>
                    <span>${escapeHtml(text("Use", "使用"))}</span>
                </button>
            </article>
        `).join("");
    }

    function setTextboxValue(rootId, value) {
        if (typeof setGradioTextboxValue === "function" && setGradioTextboxValue(rootId, value)) return true;
        const root = typeof getGradioRootById === "function" ? getGradioRootById(rootId) : document.getElementById(rootId);
        const field = root?.querySelector?.("textarea, input");
        if (!field) return false;
        field.value = value;
        field.dispatchEvent(new Event("input", { bubbles: true }));
        field.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
    }

    function currentTextboxValue(rootId) {
        const root = typeof getGradioRootById === "function" ? getGradioRootById(rootId) : document.getElementById(rootId);
        const field = root?.querySelector?.("textarea, input");
        return String(field?.value || "");
    }

    function applyPromptItem(item) {
        const target = item.target || "positive_prompt";
        const incoming = String(item.prompt || "").trim();
        if (!incoming) return;
        const mode = item.mode === "append" ? "append" : "replace";
        let next = incoming;
        if (mode === "append") {
            const current = currentTextboxValue(target).trim();
            next = current ? `${current}, ${incoming}` : incoming;
        }
        if (setTextboxValue(target, next)) {
            if (target === "positive_prompt" && typeof syncPositivePromptMetaState === "function") {
                try { syncPositivePromptMetaState(); } catch (e) {}
            }
            closeModal();
        }
    }

    function rememberRandomPrompt(item) {
        if (item?.source !== "developer_nsfw_random_prompt") return;
        const recipe = item.recipe && typeof item.recipe === "object" ? item.recipe : {};
        const axes = recipe.axes && typeof recipe.axes === "object" ? recipe.axes : {};
        const tags = String(item.prompt || "")
            .split(",")
            .map((tag) => tag.trim())
            .filter(Boolean)
            .slice(0, RANDOM_HISTORY_TAG_LIMIT);
        recentRandomHistory.push({
            profile: String(recipe.profile || ""),
            content_level: String(recipe.content_level || ""),
            axes: Object.assign({}, axes),
            tags,
        });
        if (recentRandomHistory.length > RANDOM_HISTORY_LIMIT) {
            recentRandomHistory = recentRandomHistory.slice(-RANDOM_HISTORY_LIMIT);
        }
    }

    async function openRecommendations() {
        const preset = currentPreset();
        const sceneTheme = selectedSceneTheme();
        renderItems([], preset, sceneTheme);
        const node = ensureModal();
        node.querySelector('[data-role="list"]').innerHTML = `<div class="simpleai-prompt-recommendation-empty">${escapeHtml(text("Loading...", "加载中..."))}</div>`;
        node.classList.add("is-open");
        node.removeAttribute("aria-hidden");
        try {
            const payload = await postJson("/simpleai/prompt-recommendations", {
                preset,
                scene_theme: sceneTheme,
                __lang: currentLang(),
                limit: 24,
            });
            renderItems(payload.items || [], payload.preset || preset, payload.scene_theme || sceneTheme);
        } catch (error) {
            node.querySelector('[data-role="list"]').innerHTML = `<div class="simpleai-prompt-recommendation-empty">${escapeHtml(error.message || String(error))}</div>`;
        }
    }

    async function generateRandomPrompt() {
        if (randomPromptPending) return;
        randomPromptPending = true;
        const button = promptButton();
        const previous = button?.textContent || "";
        if (button) button.textContent = text("Working...", "生成中...");
        try {
            const payload = await postJson("/simpleai/random-prompt", {
                preset: currentPreset(),
                scene_theme: selectedSceneTheme(),
                __lang: currentLang(),
                prompt_head: currentTextboxValue("positive_prompt").slice(0, 64),
                recent_history: recentRandomHistory,
            });
            if (payload.item) {
                rememberRandomPrompt(payload.item);
                applyPromptItem(payload.item);
            }
        } catch (error) {
            console.warn("[UI-TRACE] random_prompt.local_failed", error);
        } finally {
            randomPromptPending = false;
            if (button) button.textContent = previous || text("Random Prompt", "随机提示词");
            setPromptButtonLabel();
        }
    }

    function onRandomPromptClick(evt) {
        const button = promptButton();
        if (!button || evt.target !== button && !button.contains(evt.target)) return;
        evt.preventDefault();
        evt.stopPropagation();
        if (isSceneMode()) {
            openRecommendations();
        } else {
            generateRandomPrompt();
        }
    }

    function bindButton() {
        const button = promptButton();
        setPromptButtonLabel();
        if (!button || clickBoundButton === button) return;
        if (clickBoundButton) clickBoundButton.removeEventListener("click", onRandomPromptClick, true);
        button.addEventListener("click", onRandomPromptClick, true);
        clickBoundButton = button;
    }

    document.addEventListener("keydown", (evt) => {
        if (evt.key === "Escape") closeModal();
    });

    window.refreshSimpleAIPromptRecommendationButton = function refreshSimpleAIPromptRecommendationButton() {
        bindButton();
    };

    if (typeof onUiLoaded === "function") onUiLoaded(bindButton);
    if (typeof onAfterUiUpdate === "function") onAfterUiUpdate(bindButton);
})();
