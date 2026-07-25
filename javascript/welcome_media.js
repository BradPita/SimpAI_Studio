(function () {
    "use strict";

    const state = {
        busy: false,
        observer: null,
        observedPreview: null,
        scheduled: false,
    };

    function appRoot() {
        try {
            return typeof gradioApp === "function" ? gradioApp() : document;
        } catch (e) {
            return document;
        }
    }

    function byId(id) {
        const app = appRoot();
        return (app && app.getElementById ? app.getElementById(id) : null) || document.getElementById(id);
    }

    function currentLanguage() {
        const topbarState = window.simpleaiTopbarSystemParams && typeof window.simpleaiTopbarSystemParams === "object"
            ? window.simpleaiTopbarSystemParams
            : {};
        const raw = String(topbarState.__lang || "en").toLowerCase();
        return raw.startsWith("cn") || raw.startsWith("zh") ? "cn" : "en";
    }

    function text(english, chinese) {
        return currentLanguage() === "cn" ? chinese : english;
    }

    function imageSource(root) {
        try {
            const image = root && root.querySelector ? root.querySelector("img") : null;
            return image ? (image.currentSrc || image.src || image.getAttribute("src") || "") : "";
        } catch (e) {
            return "";
        }
    }

    function normalizedSource(value) {
        let source = String(value || "").trim().replace(/\\/g, "/");
        try {
            source = decodeURIComponent(source);
        } catch (e) {
        }
        return source.split("#", 1)[0].split("?", 1)[0].toLowerCase();
    }

    function bridgeSource(kind) {
        return imageSource(byId(`welcome_media_${kind}_source`));
    }

    function sourceMatches(left, right) {
        const a = normalizedSource(left);
        const b = normalizedSource(right);
        return !!a && !!b && (a === b || a.endsWith(b) || b.endsWith(a));
    }

    function isCustomSource(source, kind) {
        const value = normalizedSource(source);
        if (value.includes(`/studio_ui/welcome/${kind}-`)) return true;
        return new RegExp(`(?:^|/)${kind}-(?:desktop|mobile)-[0-9a-f]{16}\\.webp$`).test(value);
    }

    function classifySource(source) {
        if (!source) return "";
        if (sourceMatches(source, bridgeSource("waiting"))) return "waiting";
        if (sourceMatches(source, bridgeSource("title"))) return "title";

        if (isCustomSource(source, "waiting")) return "waiting";
        if (isCustomSource(source, "title")) return "title";

        const value = normalizedSource(source);
        if (/(?:^|\/)(?:\d+_)?welcome_0_[wm]\.(?:jpe?g|png|gif|webp)$/.test(value)) return "waiting";
        if (value.includes("/presets/welcome/") && !value.includes("welcome_0_")) return "title";
        if (/(?:^|\/)(?:\d+_)?welcome(?:_(?:[^/]+_)?[wm])?\.(?:jpe?g|png|gif|webp)$/.test(value)) return "title";
        return "";
    }

    function currentKind() {
        return classifySource(imageSource(byId("preview_generating")));
    }

    function actionKind(button) {
        const actions = button && button.closest ? button.closest(".simpleai-welcome-media-actions") : null;
        return actions ? String(actions.dataset.welcomeMediaKind || "") : "";
    }

    function setNativeValue(field, value) {
        if (!field) return false;
        try {
            const prototype = field instanceof HTMLTextAreaElement
                ? HTMLTextAreaElement.prototype
                : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
            if (setter) setter.call(field, value);
            else field.value = value;
            field.dispatchEvent(new Event("input", { bubbles: true }));
            field.dispatchEvent(new Event("change", { bubbles: true }));
            return true;
        } catch (e) {
            return false;
        }
    }

    function setTarget(kind) {
        const root = byId("welcome_media_target");
        const field = root && root.querySelector ? root.querySelector("textarea, input") : null;
        return setNativeValue(field, kind);
    }

    function actionLabels(kind) {
        if (kind === "waiting") {
            return {
                replace: text("Replace generation waiting image", "替换生成等待图片"),
                restore: text("Restore default generation waiting image", "恢复默认生成等待图片"),
            };
        }
        return {
            replace: text("Replace title image", "替换标题图片"),
            restore: text("Restore default title image", "恢复默认标题图片"),
        };
    }

    function setBusy(value) {
        state.busy = !!value;
        document.querySelectorAll(".simpleai-welcome-media-actions").forEach((actions) => {
            actions.classList.toggle("is-busy", state.busy);
            actions.querySelectorAll("button").forEach((button) => {
                button.disabled = state.busy;
                button.setAttribute("aria-busy", state.busy ? "true" : "false");
            });
            const icon = actions.querySelector("[data-welcome-media-action='replace'] i");
            if (icon) {
                icon.className = state.busy ? "fa-solid fa-spinner fa-spin" : "fa-solid fa-image";
            }
        });
    }

    function bindUploadInput() {
        const root = byId("welcome_media_upload");
        const input = root && root.querySelector ? root.querySelector("input[type='file']") : null;
        if (!input || input.dataset.simpleaiWelcomeMediaBound === "1") return input;
        input.dataset.simpleaiWelcomeMediaBound = "1";
        input.addEventListener("change", () => {
            if (input.files && input.files.length) setBusy(true);
        }, true);
        return input;
    }

    function openPicker(kind) {
        if (state.busy || !setTarget(kind)) return;
        const input = bindUploadInput();
        if (!input) return;
        try {
            input.value = "";
        } catch (e) {
        }
        input.click();
    }

    function restoreDefault(kind) {
        if (state.busy || !setTarget(kind)) return;
        const root = byId("welcome_media_restore_bridge");
        const button = root && root.matches && root.matches("button")
            ? root
            : (root && root.querySelector ? root.querySelector("button") : null);
        if (!button) return;
        setBusy(true);
        window.setTimeout(() => button.click(), 0);
    }

    function ensureActions(surface, surfaceName) {
        if (!surface) return null;
        let actions = surface.querySelector(".simpleai-welcome-media-actions");
        if (actions) return actions;

        actions = document.createElement("div");
        if (surfaceName === "preview") actions.id = "simpleai_welcome_media_actions";
        else actions.id = `simpleai_welcome_media_actions_${surfaceName}`;
        actions.className = "simpleai-welcome-media-actions";
        actions.dataset.welcomeMediaSurface = surfaceName;

        const replaceButton = document.createElement("button");
        replaceButton.type = "button";
        replaceButton.className = "simpleai-welcome-media-action simpleai-welcome-media-replace";
        replaceButton.dataset.welcomeMediaAction = "replace";
        replaceButton.innerHTML = '<i class="fa-solid fa-image" aria-hidden="true"></i>';
        replaceButton.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const kind = actionKind(event.currentTarget);
            if (kind) openPicker(kind);
        });

        const restoreButton = document.createElement("button");
        restoreButton.type = "button";
        restoreButton.className = "simpleai-welcome-media-action simpleai-welcome-media-restore";
        restoreButton.dataset.welcomeMediaAction = "restore";
        restoreButton.innerHTML = '<i class="fa-solid fa-arrow-rotate-left" aria-hidden="true"></i>';
        restoreButton.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const kind = actionKind(event.currentTarget);
            if (kind) restoreDefault(kind);
        });

        actions.append(replaceButton, restoreButton);
        surface.appendChild(actions);
        return actions;
    }

    function syncSurface(surface, surfaceName) {
        if (!surface) return;
        const actions = ensureActions(surface, surfaceName);
        if (!actions) return;

        const surfaceSource = imageSource(surface);
        const kind = surfaceName === "preview" ? currentKind() : classifySource(surfaceSource);
        actions.classList.toggle("is-active", !!kind);
        actions.dataset.welcomeMediaKind = kind;
        surface.dataset.simpleaiWelcomeMediaKind = kind;

        const labels = actionLabels(kind);
        const replaceButton = actions.querySelector("[data-welcome-media-action='replace']");
        const restoreButton = actions.querySelector("[data-welcome-media-action='restore']");
        if (replaceButton) {
            replaceButton.title = labels.replace;
            replaceButton.setAttribute("aria-label", labels.replace);
        }
        if (restoreButton) {
            restoreButton.title = labels.restore;
            restoreButton.setAttribute("aria-label", labels.restore);
            restoreButton.hidden = !kind || !(
                isCustomSource(surfaceSource, kind)
                || isCustomSource(bridgeSource(kind), kind)
            );
        }
    }

    function sync() {
        state.scheduled = false;
        const preview = byId("preview_generating");
        bindUploadInput();
        syncSurface(preview, "preview");
        syncSurface(byId("simpleai_gallery_welcome_guard_placeholder"), "gallery_placeholder");
        setBusy(state.busy);
        ensureObserver();
    }

    function scheduleSync() {
        if (state.scheduled) return;
        state.scheduled = true;
        window.requestAnimationFrame(sync);
    }

    function ensureObserver() {
        const preview = byId("preview_generating");
        if (!preview || preview === state.observedPreview) return;
        if (state.observer) state.observer.disconnect();
        state.observedPreview = preview;
        if (typeof MutationObserver !== "function") return;
        state.observer = new MutationObserver(scheduleSync);
        state.observer.observe(preview, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ["src", "class", "style"],
        });
    }

    function begin(kind) {
        if (kind) setTarget(kind);
        setBusy(true);
    }

    function refreshGalleryPlaceholder() {
        if (!byId("simpleai_gallery_welcome_guard_placeholder")) return;
        try {
            if (typeof window.ensureFinishedGalleryWelcomePlaceholder === "function") {
                window.ensureFinishedGalleryWelcomePlaceholder();
            }
        } catch (e) {
        }
    }

    function finish() {
        setBusy(false);
        refreshGalleryPlaceholder();
        scheduleSync();
        window.setTimeout(() => {
            refreshGalleryPlaceholder();
            scheduleSync();
        }, 80);
        window.setTimeout(() => {
            refreshGalleryPlaceholder();
            scheduleSync();
        }, 240);
    }

    window.SimpAIWelcomeMedia = {
        begin,
        finish,
        sync: scheduleSync,
        getSource: bridgeSource,
        classifySource,
        isSource(source, kind) {
            return classifySource(source) === kind;
        },
    };
    window.getStudioWelcomeMediaSource = bridgeSource;
    window.isStudioWelcomeMediaSource = function (source, kind) {
        return classifySource(source) === kind;
    };

    if (typeof onUiLoaded === "function") onUiLoaded(scheduleSync);
    if (typeof onAfterUiUpdate === "function") onAfterUiUpdate(scheduleSync);
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", scheduleSync, { once: true });
    else scheduleSync();
})();
