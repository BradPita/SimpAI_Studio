(function () {
    'use strict';

    const UTILS = window.SimpAICanvasWorkbenchUtils || {};
    const t = UTILS.t || ((en, cn) => cn || en);
    const escapeHtml = UTILS.escapeHtml || ((value) => String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;'));
    const getUiLang = UTILS.getUiLang || (() => 'cn');

    const MAX_ATTACHMENTS = 5;
    const MAX_HISTORY_TURNS = 18;
    const HISTORY_BUDGET = 6200;
    const FULL_HISTORY_BUDGET = 9000;
    const DESCRIBE_VLM_MODEL_CHOICES = [
        'Qwen3.5-9B-abliterated-Q4_K_M',
        'Qwen3.5-9B-abliterated-Q2_K',
        'Qwen3.5-9B-abliterated-Q6_K',
        'Qwen3.5-9B-abliterated-Q8_0',
        'Custom'
    ];
    const ONE_PIXEL_IMAGE = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';
    const SETTINGS_STORAGE_KEY = 'simpai.describeVlmChat.settings.v1';
    const SYSTEM_PROMPT_TEMPLATE_ENDPOINT = '/vlm-system-prompt-templates';

    function normalizeChatMode(value) {
        const mode = String(value || '').trim().toLowerCase().replace(/-/g, '_');
        if (mode === 'prompt' || mode === 'prompt_assistant' || mode === 'assistant') return 'prompt';
        if (mode === 'guide' || mode === 'guide_mode' || mode === 'wizard' || mode === 'ui_guide') return 'guide';
        if (mode === 'raw' || mode === 'raw_model') return 'raw';
        return 'chat';
    }

    function normalizeChatWindowLayout(value) {
        if (!value || typeof value !== 'object') return null;
        const finite = (item) => {
            const number = Number(item);
            return Number.isFinite(number) && number > 0 ? Math.round(number) : null;
        };
        const left = finite(value.left);
        const top = finite(value.top);
        const width = finite(value.width);
        const height = finite(value.height);
        if (left === null && top === null && width === null && height === null) return null;
        return {
            left,
            top,
            width,
            height,
            moved: !!value.moved,
            resized: !!value.resized
        };
    }

    function loadChatSettings() {
        try {
            const data = JSON.parse(window.localStorage?.getItem(SETTINGS_STORAGE_KEY) || '{}');
            return {
                chatMode: normalizeChatMode(data.chatMode),
                customSystemPrompt: String(data.customSystemPrompt || ''),
                systemPromptTemplateId: String(data.systemPromptTemplateId || ''),
                unloadAfterChat: !!data.unloadAfterChat,
                windowLayout: normalizeChatWindowLayout(data.windowLayout)
            };
        } catch (err) {
            return { chatMode: 'chat', customSystemPrompt: '', systemPromptTemplateId: '', unloadAfterChat: false, windowLayout: null };
        }
    }

    const savedChatSettings = loadChatSettings();
    let modalBackdropPointerStarted = false;

    const state = {
        conversationId: '',
        messages: [],
        busy: false,
        requestToken: 0,
        activeAbortController: null,
        activeRequestId: '',
        lastImageKey: '',
        useImage: true,
        pendingImages: [],
        missingVlmModelRequest: null,
        chatMode: savedChatSettings.chatMode,
        customSystemPrompt: savedChatSettings.customSystemPrompt,
        systemPromptTemplateId: savedChatSettings.systemPromptTemplateId,
        systemPromptTemplates: [],
        systemPromptTemplatesLoaded: false,
        systemPromptTemplatesLoading: false,
        unloadAfterChat: !!savedChatSettings.unloadAfterChat,
        windowLayout: savedChatSettings.windowLayout
    };

    function root() {
        try {
            return typeof gradioApp === 'function' ? gradioApp() : document;
        } catch (err) {
            return document;
        }
    }

    function uid(prefix) {
        return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(16).slice(2, 8)}`;
    }

    function ensureConversationId() {
        if (!state.conversationId) state.conversationId = uid('describe_vlm_chat');
        return state.conversationId;
    }

    function localText(en, cn) {
        const lang = String(getUiLang?.() || '').toLowerCase();
        return lang.startsWith('zh') || lang.startsWith('cn') ? cn : en;
    }

    function saveChatSettings() {
        try {
            window.localStorage?.setItem(SETTINGS_STORAGE_KEY, JSON.stringify({
                chatMode: state.chatMode,
                customSystemPrompt: state.customSystemPrompt,
                systemPromptTemplateId: state.systemPromptTemplateId,
                unloadAfterChat: !!state.unloadAfterChat,
                windowLayout: state.windowLayout || null
            }));
        } catch (err) {
            // Ignore storage failures in private or restricted browser contexts.
        }
    }

    function chatInputPlaceholder(mode) {
        const currentMode = normalizeChatMode(mode);
        if (currentMode === 'prompt') {
            return t('Ask it to prepare or refine a prompt...', '让它整理或优化提示词...');
        }
        if (currentMode === 'guide') {
            return t('Ask which SimpAI workflow or feature to use...', '询问该使用 SimpAI 的哪个流程或功能...');
        }
        if (currentMode === 'raw') {
            return t('Raw model chat...', '原始模型对话...');
        }
        return t('Chat naturally, ask about the image, or request a prompt...', '正常聊天、询问图片，或要求整理提示词...');
    }

    function defaultMessageForMode(mode) {
        const currentMode = normalizeChatMode(mode);
        if (currentMode === 'prompt') {
            return t('Please analyze the attached reference image and prepare a prompt.', '请分析附加引用图，并整理成提示词。');
        }
        if (currentMode === 'guide') {
            return t('Please recommend a suitable SimpAI workflow for this image.', '请根据这张图推荐适合的 SimpAI 工作流。');
        }
        return t('Please analyze the attached reference image.', '请分析附加引用图。');
    }

    function shouldSendCurrentPromptToVlm(mode, message) {
        return normalizeChatMode(mode) === 'prompt';
    }

    function syncChatSettingsControls(modal) {
        if (!modal) return;
        const mode = modal.querySelector('[data-describe-vlm-chat-mode]');
        const system = modal.querySelector('[data-describe-vlm-chat-system]');
        const template = modal.querySelector('[data-describe-vlm-chat-template]');
        const input = modal.querySelector('[data-describe-vlm-chat-input]');
        const unload = modal.querySelector('[data-describe-vlm-chat-unload-after]');
        const modeHint = modal.querySelector('[data-describe-vlm-chat-mode-hint]');
        if (mode) mode.value = state.chatMode;
        if (system && system.value !== state.customSystemPrompt) system.value = state.customSystemPrompt;
        if (template) syncSystemPromptTemplateControls(modal);
        if (unload) unload.checked = !!state.unloadAfterChat;
        if (modeHint) modeHint.hidden = state.chatMode !== 'chat';
        if (input) input.setAttribute('placeholder', chatInputPlaceholder(state.chatMode));
        updateAnswerModelIndicator(modal);
    }

    function componentHost(elemId) {
        const safeId = CSS.escape(elemId);
        const app = (typeof window.gradioApp === 'function') ? window.gradioApp() : null;
        return root().querySelector(`#${safeId}`)
            || app?.getElementById?.(elemId)
            || app?.querySelector?.(`#${safeId}`)
            || document.getElementById(elemId);
    }

    function componentInput(elemId) {
        const host = componentHost(elemId);
        return host?.matches?.('textarea,input,select')
            ? host
            : host?.querySelector?.('textarea,input,select');
    }

    function setComponentValue(elemId, value) {
        const input = componentInput(elemId);
        if (!input) return false;
        const proto = input instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype
            : input instanceof HTMLSelectElement
                ? HTMLSelectElement.prototype
                : HTMLInputElement.prototype;
        const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
        if (descriptor?.set) descriptor.set.call(input, String(value ?? ''));
        else input.value = String(value ?? '');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
    }

    function readComponentValue(elemId) {
        const input = componentInput(elemId);
        if (input) return input.value || '';
        const host = componentHost(elemId);
        const selected = host?.querySelector?.('[aria-selected="true"], [data-selected="true"], .selected');
        return selected?.textContent?.trim() || host?.textContent?.trim() || '';
    }

    function readCheckboxValue(elemId, fallback = false) {
        const host = componentHost(elemId);
        const input = host?.matches?.('input[type="checkbox"]')
            ? host
            : host?.querySelector?.('input[type="checkbox"]');
        return input ? !!input.checked : !!fallback;
    }

    function clickComponentButton(elemId) {
        const host = componentHost(elemId);
        const button = host?.matches?.('button') ? host : host?.querySelector?.('button');
        if (!button) return false;
        try {
            button.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
            button.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
            button.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
            button.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
        } catch (err) {}
        button.click();
        return true;
    }

    async function postJson(endpoint, payload, options = {}) {
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload || {}),
                signal: options?.signal
            });
            let data = null;
            try {
                data = await response.json();
            } catch (err) {
                data = null;
            }
            if (!response.ok) {
                return Object.assign({}, data || {}, {
                    ok: false,
                    error: data?.error || `HTTP ${response.status}`,
                    details: data?.details || response.statusText || ''
                });
            }
            return data || { ok: false, error: 'empty response' };
        } catch (err) {
            if (err?.name === 'AbortError') {
                return { ok: false, aborted: true, error: 'aborted' };
            }
            return { ok: false, error: err?.message || String(err || 'request failed') };
        }
    }

    function normalizeSystemPromptTemplates(data) {
        const rows = Array.isArray(data?.templates) ? data.templates : [];
        return rows.map((item) => {
            const id = String(item?.id || item?.filename || item?.name || '').trim();
            const name = String(item?.name || item?.filename || id).trim();
            const content = String(item?.content || '').trim();
            if (!id || !name || !content) return null;
            return { id, name, filename: String(item?.filename || id), content };
        }).filter(Boolean);
    }

    function selectedSystemPromptTemplateIdForContent(content) {
        const text = String(content || '').trim();
        if (!text) return '';
        const match = state.systemPromptTemplates.find(item => String(item.content || '').trim() === text);
        return match?.id || '';
    }

    function renderSystemPromptTemplateOptions() {
        const selected = state.systemPromptTemplateId || selectedSystemPromptTemplateIdForContent(state.customSystemPrompt);
        const intro = state.systemPromptTemplatesLoading && !state.systemPromptTemplatesLoaded
            ? t('Loading templates...', '正在读取模板...')
            : t('Custom / no template', '自定义 / 不使用模板');
        const options = [`<option value="">${escapeHtml(intro)}</option>`];
        state.systemPromptTemplates.forEach((item) => {
            options.push(`<option value="${escapeHtml(item.id)}" ${item.id === selected ? 'selected' : ''}>${escapeHtml(item.name)}</option>`);
        });
        return options.join('');
    }

    function syncSystemPromptTemplateControls(modal) {
        const target = modal || document.getElementById('describe_vlm_chat_modal');
        if (!target) return;
        target.querySelectorAll('[data-describe-vlm-chat-template]').forEach((select) => {
            const activeId = state.systemPromptTemplateId || selectedSystemPromptTemplateIdForContent(state.customSystemPrompt);
            select.innerHTML = renderSystemPromptTemplateOptions();
            select.value = activeId;
            select.disabled = state.systemPromptTemplatesLoading && !state.systemPromptTemplatesLoaded;
        });
    }

    let systemPromptTemplateRequest = null;

    async function ensureSystemPromptTemplates(modal) {
        if (state.systemPromptTemplatesLoaded) {
            syncSystemPromptTemplateControls(modal);
            return state.systemPromptTemplates;
        }
        if (systemPromptTemplateRequest) return systemPromptTemplateRequest;
        state.systemPromptTemplatesLoading = true;
        syncSystemPromptTemplateControls(modal);
        systemPromptTemplateRequest = postJson(SYSTEM_PROMPT_TEMPLATE_ENDPOINT, {})
            .then((data) => {
                state.systemPromptTemplates = normalizeSystemPromptTemplates(data);
                state.systemPromptTemplatesLoaded = true;
                state.systemPromptTemplatesLoading = false;
                syncSystemPromptTemplateControls(modal);
                return state.systemPromptTemplates;
            })
            .catch(() => {
                state.systemPromptTemplates = [];
                state.systemPromptTemplatesLoaded = true;
                state.systemPromptTemplatesLoading = false;
                syncSystemPromptTemplateControls(modal);
                return [];
            })
            .finally(() => {
                systemPromptTemplateRequest = null;
            });
        return systemPromptTemplateRequest;
    }

    function applySystemPromptTemplate(templateId, modal) {
        const id = String(templateId || '').trim();
        if (!id) {
            const target = modal || document.getElementById('describe_vlm_chat_modal');
            const textarea = target?.querySelector?.('[data-describe-vlm-chat-system]');
            const currentText = String(textarea?.value ?? state.customSystemPrompt ?? '').trim();
            const matchedTemplate = state.systemPromptTemplates.find(item => item.id === state.systemPromptTemplateId)
                || state.systemPromptTemplates.find(item => String(item.content || '').trim() === currentText);
            const shouldClearPrompt = !!matchedTemplate && String(matchedTemplate.content || '').trim() === currentText;
            state.systemPromptTemplateId = '';
            if (shouldClearPrompt) state.customSystemPrompt = '';
            if (textarea && shouldClearPrompt) textarea.value = '';
            saveChatSettings();
            syncSystemPromptTemplateControls(target);
            if (shouldClearPrompt) setStatus(t('System prompt template cleared.', '系统提示词模板已清除。'));
            return;
        }
        const template = state.systemPromptTemplates.find(item => item.id === id);
        if (!template) return;
        state.systemPromptTemplateId = template.id;
        state.customSystemPrompt = template.content;
        const target = modal || document.getElementById('describe_vlm_chat_modal');
        const textarea = target?.querySelector?.('[data-describe-vlm-chat-system]');
        if (textarea) textarea.value = state.customSystemPrompt;
        saveChatSettings();
        syncSystemPromptTemplateControls(target);
        setStatus(t('System prompt template loaded: {name}', '已载入系统提示词模板：{name}').replace('{name}', template.name));
    }

    function currentImageElement() {
        const host = root().querySelector('#describe_input_image');
        const images = Array.from(host?.querySelectorAll?.('img') || []);
        return images.find((img) => img?.src && img.naturalWidth && img.naturalHeight) || images.find((img) => img?.src) || null;
    }

    function imageMimeFromDataUrl(dataUrl) {
        const match = String(dataUrl || '').match(/^data:([^;,]+)/);
        return match ? match[1] : 'image/png';
    }

    function blobToDataUrl(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ''));
            reader.onerror = () => reject(reader.error || new Error('read image failed'));
            reader.readAsDataURL(blob);
        });
    }

    function loadImage(dataUrl) {
        return new Promise((resolve, reject) => {
            const image = new Image();
            image.onload = () => resolve(image);
            image.onerror = () => reject(new Error('image decode failed'));
            image.src = dataUrl;
        });
    }

    function scaledSize(width, height, maxSide) {
        const w = Math.max(1, Number(width) || 1);
        const h = Math.max(1, Number(height) || 1);
        const scale = Math.min(1, Math.max(1, Number(maxSide) || 1) / Math.max(w, h));
        return {
            width: Math.max(1, Math.round(w * scale)),
            height: Math.max(1, Math.round(h * scale))
        };
    }

    function drawImageDataUrl(image, maxSide, mime, quality) {
        const size = scaledSize(image.naturalWidth || image.width, image.naturalHeight || image.height, maxSide);
        const canvas = document.createElement('canvas');
        canvas.width = size.width;
        canvas.height = size.height;
        const ctx = canvas.getContext('2d', { alpha: String(mime || '').includes('png') });
        if (!String(mime || '').includes('png')) {
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, size.width, size.height);
        }
        ctx.drawImage(image, 0, 0, size.width, size.height);
        return {
            dataUrl: canvas.toDataURL(mime || 'image/jpeg', quality == null ? 0.88 : quality),
            width: size.width,
            height: size.height
        };
    }

    async function imagePayloadFromDataUrl(dataUrl, options = {}) {
        const sourceMime = options.mime || imageMimeFromDataUrl(dataUrl);
        try {
            const image = await loadImage(dataUrl);
            const outputMime = sourceMime === 'image/png' ? 'image/png' : 'image/jpeg';
            const main = drawImageDataUrl(image, 1280, outputMime, 0.88);
            const thumb = drawImageDataUrl(image, 96, 'image/jpeg', 0.76);
            return {
                id: options.id || uid('describe_ref'),
                name: options.name || 'reference-image.png',
                mime: imageMimeFromDataUrl(main.dataUrl),
                width: main.width,
                height: main.height,
                size: options.size || Math.round((main.dataUrl.length * 3) / 4),
                data_url: main.dataUrl,
                thumb: thumb.dataUrl,
                key: options.key || `${options.name || 'image'}:${main.width}x${main.height}:${main.dataUrl.length}`
            };
        } catch (err) {
            return {
                id: options.id || uid('describe_ref'),
                name: options.name || 'reference-image.png',
                mime: sourceMime,
                width: options.width || null,
                height: options.height || null,
                size: options.size || Math.round((String(dataUrl).length * 3) / 4),
                data_url: dataUrl,
                thumb: '',
                key: options.key || String(dataUrl).slice(0, 180)
            };
        }
    }

    async function currentImagePayload() {
        const img = currentImageElement();
        if (!img?.src) return null;
        const src = img.currentSrc || img.src;
        let dataUrl = '';
        if (/^data:/i.test(src)) {
            dataUrl = src;
        } else {
            const response = await fetch(src);
            const blob = await response.blob();
            dataUrl = await blobToDataUrl(blob);
        }
        if (!dataUrl) return null;
        return imagePayloadFromDataUrl(dataUrl, {
            id: uid('describe_img'),
            name: 'describe-image.png',
            mime: imageMimeFromDataUrl(dataUrl),
            width: img.naturalWidth || null,
            height: img.naturalHeight || null,
            key: src
        });
    }

    async function fileToImagePayload(file) {
        const dataUrl = await blobToDataUrl(file);
        return imagePayloadFromDataUrl(dataUrl, {
            id: uid('describe_ref'),
            name: file.name || 'reference-image.png',
            mime: file.type || imageMimeFromDataUrl(dataUrl),
            size: file.size || null,
            key: `${file.name || 'image'}:${file.size || 0}:${file.lastModified || 0}`
        });
    }

    function cleanVlmVersion(value) {
        const text = String(value || '').replace(/[✓✔⚠⬇↓]/g, '').trim();
        if (/(^|\s)Custom($|\s)/i.test(text)) return 'Custom';
        return text;
    }

    function currentCustomVlmModelName() {
        return String(readComponentValue('describe_vlm_custom_model') || '').trim();
    }

    function customVlmModelOptionLabel() {
        return currentCustomVlmModelName() || 'Custom';
    }

    function customVlmModelLabelIsBetter(nextLabel, currentLabel) {
        const next = String(nextLabel || '').replace(/[✓✔⚠⬇↓]/g, '').trim();
        const current = String(currentLabel || '').replace(/[✓✔⚠⬇↓]/g, '').trim();
        return !!next && !/(^|\s)Custom($|\s)/i.test(next) && ((/^Custom$/i).test(current) || !current);
    }

    function customVlmOptionValue(rawValue, label) {
        const value = cleanVlmVersion(rawValue || label);
        if (value === 'Custom') return value;
        const customModel = currentCustomVlmModelName();
        const cleanLabel = String(label || rawValue || '').replace(/[✓✔⚠⬇↓]/g, '').trim();
        if (customModel && (cleanLabel === customModel || cleanLabel.endsWith(`· ${customModel}`))) return 'Custom';
        return value;
    }

    function addUniqueVlmModelOption(options, option) {
        const value = customVlmOptionValue(option?.value, option?.label);
        if (!value) return;
        const existing = options.find((item) => item.value === value);
        if (existing) {
            const label = String(option?.label || option?.value || value).trim() || value;
            if (value === 'Custom' && customVlmModelLabelIsBetter(label, existing.label)) existing.label = label;
            return;
        }
        options.push({
            value,
            label: String(option?.label || option?.value || value).trim() || value
        });
    }

    function nativeVlmDropdownOptions(elemId) {
        const host = componentHost(elemId);
        const select = host?.matches?.('select') ? host : host?.querySelector?.('select');
        if (!select) return [];
        return Array.from(select.options || [])
            .map((option) => {
                const label = String(option.textContent || option.value || '').trim();
                const value = customVlmOptionValue(option.value, label);
                return value ? { value, label: label || value } : null;
            })
            .filter(Boolean);
    }

    function registryVlmDropdownOptions() {
        const registry = window.SimpAICanvasWorkbenchRegistry || window.SimpAICanvasWorkbenchVlm || {};
        const choices = Array.isArray(registry.VLM_VERSION_CHOICES) && registry.VLM_VERSION_CHOICES.length
            ? registry.VLM_VERSION_CHOICES
            : DESCRIBE_VLM_MODEL_CHOICES;
        return choices.map((choice) => ({ value: cleanVlmVersion(choice), label: String(choice || '').trim() }))
            .filter((choice) => choice.value);
    }

    function describeVlmModelOptions() {
        const options = [];
        nativeVlmDropdownOptions('describe_vlm_model_dropdown').forEach((option) => addUniqueVlmModelOption(options, option));
        nativeVlmDropdownOptions('describe_vlm_model').forEach((option) => addUniqueVlmModelOption(options, option));
        registryVlmDropdownOptions().forEach((option) => addUniqueVlmModelOption(options, option));
        const current = cleanVlmVersion(readSelectedVlmVersion());
        if (current) addUniqueVlmModelOption(options, { value: current, label: current });
        addUniqueVlmModelOption(options, { value: 'Custom', label: customVlmModelOptionLabel() });
        return options;
    }

    function syncHeaderVlmModelSelect(select, selectedVersion) {
        if (!select) return;
        const options = describeVlmModelOptions();
        const signature = options.map((option) => `${option.value}\u001f${option.label}`).join('\u001e');
        if (select.dataset.describeVlmModelChoices !== signature) {
            select.innerHTML = options
                .map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`)
                .join('');
            select.dataset.describeVlmModelChoices = signature;
        }
        const version = cleanVlmVersion(selectedVersion || readSelectedVlmVersion());
        if (version && Array.from(select.options || []).some((option) => option.value === version) && select.value !== version) {
            select.value = version;
        }
    }

    function setDescribeVlmVersionFromHeader(rawValue) {
        const version = cleanVlmVersion(rawValue);
        if (!version) return false;
        const clicked = setComponentValue('describe_vlm_model_select_bridge', version)
            && clickComponentButton('describe_vlm_model_select_btn');
        if (!clicked) {
            const option = describeVlmModelOptions().find((item) => item.value === version);
            setComponentValue('describe_vlm_model_dropdown', option?.label || version);
            setStatus(t('Model selector is unavailable. Please reload the page.', '模型选择暂不可用，请刷新页面。'), true);
        }
        updateAnswerModelIndicator();
        return clicked;
    }

    function isVisible(element) {
        if (!element) return false;
        const style = window.getComputedStyle(element);
        return style.display !== 'none' && style.visibility !== 'hidden' && element.offsetParent !== null;
    }

    function readSelectedVlmVersion() {
        const raw = readComponentValue('describe_vlm_model_dropdown') || readComponentValue('describe_vlm_model');
        const version = cleanVlmVersion(raw);
        const customPanel = componentHost('describe_vlm_custom_panel');
        if (version === 'Custom' || isVisible(customPanel)) return 'Custom';
        const customModel = String(readComponentValue('describe_vlm_custom_model') || '').trim();
        if (customModel && version === customModel) return 'Custom';
        return version;
    }

    function cleanPresetName(value) {
        return String(value || '').replace(/[\u2B07\u2193]+$/g, '').trim();
    }

    function firstTextValue(values) {
        for (const value of values || []) {
            const text = String(value || '').trim();
            if (text) return text;
        }
        return '';
    }

    function readCurrentPresetName(topbar, prepared) {
        const candidates = [];
        try {
            if (typeof topbarPendingPreset !== 'undefined' && topbarPendingPreset) candidates.push(topbarPendingPreset);
        } catch (err) {}
        try {
            if (typeof topbarLastPreset !== 'undefined' && topbarLastPreset) candidates.push(topbarLastPreset);
        } catch (err) {}
        candidates.push(topbar?.__preset, prepared?.preset, prepared?.name);
        return cleanPresetName(firstTextValue(candidates));
    }

    function readPresetStoreMeta(topbar, presetName) {
        const meta = topbar && typeof topbar.__preset_store_meta === 'object' ? topbar.__preset_store_meta : null;
        const target = cleanPresetName(presetName).toLowerCase();
        if (!meta || !target) return {};
        if (meta[presetName] && typeof meta[presetName] === 'object') return meta[presetName];
        const key = Object.keys(meta).find((item) => cleanPresetName(item).toLowerCase() === target);
        return key && typeof meta[key] === 'object' ? meta[key] : {};
    }

    function readDescribePromptOptions() {
        const topbar = window.simpleaiTopbarSystemParams && typeof window.simpleaiTopbarSystemParams === 'object'
            ? window.simpleaiTopbarSystemParams
            : {};
        const prepared = topbar.__preset_prepared && typeof topbar.__preset_prepared === 'object'
            ? topbar.__preset_prepared
            : {};
        const engine = prepared.engine && typeof prepared.engine === 'object' ? prepared.engine : {};
        const backendParams = engine.backend_params && typeof engine.backend_params === 'object' ? engine.backend_params : {};
        const presetName = readCurrentPresetName(topbar, prepared);
        const presetMeta = readPresetStoreMeta(topbar, presetName);
        return {
            output_tags: readCheckboxValue('describe_output_tags', false),
            output_chinese: readCheckboxValue('describe_output_chinese', false),
            output_artist: readCheckboxValue('describe_output_artist', false),
            preset: presetName,
            backend_engine: String(topbar.__backend_engine || topbar.backend_engine || engine.backend_engine || backendParams.backend_engine || presetMeta.backend_engine || ''),
            task_method: String(topbar.task_method || engine.task_method || backendParams.task_method || presetMeta.task_method || ''),
            prompt_format: String(topbar.prompt_format || engine.prompt_format || backendParams.prompt_format || ''),
            text_encoder: String(topbar.text_encoder || prepared.text_encoder || backendParams.text_encoder || prepared.default_clip_model || prepared.clip_model || prepared['CLIP Model'] || ''),
            base_model: String(prepared.base_model || prepared.default_model || prepared['Base Model'] || backendParams.base_model || backendParams.model || '')
        };
    }

    function readDescribeCustomApi(version) {
        if (cleanVlmVersion(version) !== 'Custom') return null;
        return {
            api_name: readComponentValue('describe_vlm_custom_api_name') || 'Custom',
            provider: readComponentValue('describe_vlm_custom_provider') || 'custom',
            api_format: readComponentValue('describe_vlm_custom_api_format') || 'openai_compatible',
            base_url: readComponentValue('describe_vlm_custom_base_url'),
            model: readComponentValue('describe_vlm_custom_model'),
            api_key: readComponentValue('describe_vlm_custom_api_key'),
            supports_images: readCheckboxValue('describe_vlm_custom_supports_images', true)
        };
    }

    function buildVlmModelStatusPayload(version) {
        const cleanVersion = cleanVlmVersion(version);
        const customApi = readDescribeCustomApi(cleanVersion);
        const params = { version: cleanVersion };
        if (customApi) {
            Object.assign(params, {
                custom_provider: customApi.provider || 'custom',
                custom_api_format: customApi.api_format || 'openai_compatible',
                custom_base_url: customApi.base_url || '',
                custom_model: customApi.model || '',
                custom_api_key: customApi.api_key || ''
            });
        }
        const payload = {
            project_id: 'describe_image_chat',
            node_id: 'describe_vlm_chat',
            params,
            user_context: window.simpleaiTopbarSystemParams || {}
        };
        if (customApi?.api_key) payload.api_key = customApi.api_key;
        return { payload, customApi };
    }

    function triggerVlmMissingModelPopup(version, customApi) {
        const cleanVersion = cleanVlmVersion(version);
        if (!cleanVersion || cleanVersion === 'Custom') return false;
        const request = {
            kind: 'vlm',
            version: cleanVersion,
            custom_api: customApi || null
        };
        if (typeof window.triggerMissingModelCheck === 'function') {
            try {
                return !!window.triggerMissingModelCheck(request);
            } catch (err) {}
        }
        if (!setComponentValue('missing_model_check_request', JSON.stringify(request))) return false;
        return clickComponentButton('missing_model_check_btn');
    }

    function showMissingVlmModelStatus(version, customApi, response, popupOpened) {
        const modal = ensureModal();
        const status = modal.querySelector('[data-describe-vlm-chat-status]');
        if (!status) return;
        const missingCount = Number(response?.missing_count || (Array.isArray(response?.missing_models) ? response.missing_models.length : 0)) || 0;
        const baseMessage = missingCount > 0
            ? t(`Selected VLM model is missing ${missingCount} file(s).`, `所选 VLM 模型缺少 ${missingCount} 个文件。`)
            : t('Selected VLM model files are missing.', '所选 VLM 模型文件缺失。');
        const actionMessage = popupOpened
            ? t('The download panel has been opened.', '下载面板已打开。')
            : t('Click the button to open the download panel.', '点击按钮打开下载面板。');
        const message = `${baseMessage} ${actionMessage}`;
        state.missingVlmModelRequest = {
            version: cleanVlmVersion(version),
            customApi: customApi || null
        };
        status.classList.add('is-error', 'is-actionable');
        status.innerHTML = `<span>${escapeHtml(message)}</span><button type="button" data-describe-vlm-chat-download-models><i class="fa-solid fa-cloud-arrow-down"></i><span>${escapeHtml(t('Open download panel', '打开下载面板'))}</span></button>`;
        if (popupOpened) {
            status.setAttribute('title', t('The download panel has been opened.', '下载面板已打开。'));
        } else {
            status.removeAttribute('title');
        }
    }

    async function ensureSelectedVlmModelReady(version) {
        const { payload, customApi } = buildVlmModelStatusPayload(version);
        const response = await postJson('/canvas-workbench/vlm-model-status', payload);
        if (response?.ok && response.ready) {
            state.missingVlmModelRequest = null;
            return true;
        }

        const missingRows = Array.isArray(response?.missing_models) ? response.missing_models : [];
        if (response?.state === 'missing' && missingRows.length) {
            const popupOpened = triggerVlmMissingModelPopup(version, customApi);
            showMissingVlmModelStatus(version, customApi, response, popupOpened);
            return false;
        }

        const message = response?.message || response?.details || response?.error || t('VLM model is not ready.', 'VLM 模型未就绪。');
        setStatus(message, true);
        return false;
    }

    function currentAnswerModelLabel() {
        const version = cleanVlmVersion(readSelectedVlmVersion());
        if (version === 'Custom') {
            const apiName = readComponentValue('describe_vlm_custom_api_name').trim();
            const customModel = readComponentValue('describe_vlm_custom_model').trim();
            if (customModel) return `${apiName || 'Custom'} · ${customModel}`;
            return apiName || 'Custom';
        }
        return version || t('No model selected', '未选择模型');
    }

    function updateAnswerModelIndicator(modal = document.getElementById('describe_vlm_chat_modal')) {
        const indicator = modal?.querySelector?.('[data-describe-vlm-chat-model]');
        const value = indicator?.querySelector?.('[data-describe-vlm-chat-model-value]');
        const select = indicator?.querySelector?.('[data-describe-vlm-chat-model-select]');
        if (!indicator) return;
        const label = currentAnswerModelLabel();
        const title = `${t('Answering model', '当前应答模型')}: ${label}`;
        if (value && value.textContent !== label) value.textContent = label;
        syncHeaderVlmModelSelect(select, readSelectedVlmVersion());
        if (indicator.getAttribute('title') !== title) indicator.setAttribute('title', title);
        if (indicator.getAttribute('aria-label') !== title) indicator.setAttribute('aria-label', title);
        if (select && select.getAttribute('aria-label') !== title) select.setAttribute('aria-label', title);
    }

    function ensureFloatingHost() {
        let host = document.getElementById('simpleai_floating_host');
        if (!host) {
            host = document.createElement('div');
            host.id = 'simpleai_floating_host';
            host.className = 'simpleai-floating-host';
            document.body.appendChild(host);
        }
        return host;
    }

    function setImportantStyle(el, name, value) {
        if (!el) return;
        el.style.setProperty(name, value, 'important');
    }

    function isFloatingModalHidden(modal) {
        if (!modal) return true;
        const style = window.getComputedStyle(modal);
        return modal.hidden
            || style.display === 'none'
            || style.visibility === 'hidden'
            || modal.classList.contains('hidden')
            || modal.classList.contains('hide');
    }

    function keepFloatingPanelInViewport(panel, margin = 12) {
        if (!panel) return;
        const rect = panel.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
        const maxLeft = Math.max(margin, window.innerWidth - margin - rect.width);
        const maxTop = Math.max(margin, window.innerHeight - margin - rect.height);
        const nextLeft = clamp(rect.left, margin, maxLeft);
        const nextTop = clamp(rect.top, margin, maxTop);
        setImportantStyle(panel, 'transform', 'none');
        setImportantStyle(panel, 'left', `${Math.round(nextLeft)}px`);
        setImportantStyle(panel, 'top', `${Math.round(nextTop)}px`);
        setImportantStyle(panel, 'right', 'auto');
        setImportantStyle(panel, 'bottom', 'auto');
    }

    function floatingResizeBoundsFrom(left, top, margin = 12) {
        const safeLeft = Math.max(margin, Number(left) || margin);
        const safeTop = Math.max(margin, Number(top) || margin);
        const maxW = Math.max(1, window.innerWidth - margin - safeLeft);
        const maxH = Math.max(1, window.innerHeight - margin - safeTop);
        return {
            minW: Math.min(420, maxW),
            minH: Math.min(420, maxH),
            maxW,
            maxH
        };
    }

    function floatingResizeViewportBounds(margin = 12) {
        const maxW = Math.max(1, window.innerWidth - margin * 2);
        const maxH = Math.max(1, window.innerHeight - margin * 2);
        return {
            minW: Math.min(420, maxW),
            minH: Math.min(420, maxH),
            maxW,
            maxH
        };
    }

    function applyFloatingPanelSize(panel, width, height, bounds, markResized = true) {
        if (!panel || !bounds) return;
        const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
        const nextW = Math.round(clamp(Number(width) || bounds.minW, bounds.minW, bounds.maxW));
        const nextH = Math.round(clamp(Number(height) || bounds.minH, bounds.minH, bounds.maxH));
        if (markResized) panel.dataset.describeVlmChatResized = '1';
        setImportantStyle(panel, 'width', `${nextW}px`);
        setImportantStyle(panel, 'height', `${nextH}px`);
        setImportantStyle(panel, 'max-width', `${Math.round(bounds.maxW)}px`);
        setImportantStyle(panel, 'max-height', `${Math.round(bounds.maxH)}px`);
    }

    function clampFloatingPanelSizeToViewport(panel, margin = 12) {
        if (!panel) return;
        const rect = panel.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        applyFloatingPanelSize(panel, rect.width, rect.height, floatingResizeViewportBounds(margin), false);
    }

    function saveFloatingPanelLayout(panel) {
        if (!panel) return;
        const rect = panel.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        state.windowLayout = {
            left: Math.round(rect.left),
            top: Math.round(rect.top),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            moved: panel.dataset.describeVlmChatMoved === '1',
            resized: panel.dataset.describeVlmChatResized === '1'
        };
        saveChatSettings();
    }

    function applySavedFloatingPanelLayout(panel, margin = 12) {
        const layout = state.windowLayout;
        if (!panel || !layout) return false;
        const bounds = floatingResizeViewportBounds(margin);
        if (Number.isFinite(layout.width) && Number.isFinite(layout.height)) {
            applyFloatingPanelSize(panel, layout.width, layout.height, bounds, false);
        }
        if (layout.resized) panel.dataset.describeVlmChatResized = '1';

        const rect = panel.getBoundingClientRect();
        if (!rect.width || !rect.height) return false;
        if (Number.isFinite(layout.left) && Number.isFinite(layout.top)) {
            const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
            const left = clamp(layout.left, margin, Math.max(margin, window.innerWidth - margin - rect.width));
            const top = clamp(layout.top, margin, Math.max(margin, window.innerHeight - margin - rect.height));
            if (layout.moved) panel.dataset.describeVlmChatMoved = '1';
            setImportantStyle(panel, 'transform', 'none');
            setImportantStyle(panel, 'left', `${Math.round(left)}px`);
            setImportantStyle(panel, 'top', `${Math.round(top)}px`);
            setImportantStyle(panel, 'right', 'auto');
            setImportantStyle(panel, 'bottom', 'auto');
        }
        return true;
    }

    function installDescribeFloatingDrag(modal, panel) {
        const handle = panel?.querySelector?.('.describe-vlm-chat-head');
        if (!modal || !panel || !handle || handle.dataset.describeVlmFloatingDragBound === '1') return;
        handle.dataset.describeVlmFloatingDragBound = '1';

        const margin = 12;
        const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
        let dragging = false;
        let offsetX = 0;
        let offsetY = 0;

        const onMove = (evt) => {
            if (!dragging) return;
            const rect = panel.getBoundingClientRect();
            if (!rect.width || !rect.height) return;
            const nextLeft = clamp(
                (evt.clientX ?? 0) - offsetX,
                margin,
                Math.max(margin, window.innerWidth - margin - rect.width)
            );
            const nextTop = clamp(
                (evt.clientY ?? 0) - offsetY,
                margin,
                Math.max(margin, window.innerHeight - margin - rect.height)
            );
            panel.dataset.describeVlmChatMoved = '1';
            setImportantStyle(panel, 'transform', 'none');
            setImportantStyle(panel, 'left', `${Math.round(nextLeft)}px`);
            setImportantStyle(panel, 'top', `${Math.round(nextTop)}px`);
            setImportantStyle(panel, 'right', 'auto');
            setImportantStyle(panel, 'bottom', 'auto');
            evt.preventDefault();
        };

        const onUp = () => {
            if (!dragging) return;
            dragging = false;
            handle.classList.remove('is-dragging');
            window.removeEventListener('pointermove', onMove, true);
            window.removeEventListener('pointerup', onUp, true);
            keepFloatingPanelInViewport(panel, margin);
            saveFloatingPanelLayout(panel);
        };

        handle.addEventListener('pointerdown', (evt) => {
            if (evt.button !== 0 || isFloatingModalHidden(modal)) return;
            if (evt.target?.closest?.('button, input, textarea, select, [role="button"]')) return;
            const rect = panel.getBoundingClientRect();
            if (!rect.width || !rect.height) return;
            dragging = true;
            offsetX = (evt.clientX ?? 0) - rect.left;
            offsetY = (evt.clientY ?? 0) - rect.top;
            handle.classList.add('is-dragging');
            window.addEventListener('pointermove', onMove, true);
            window.addEventListener('pointerup', onUp, true);
            evt.preventDefault();
        }, { passive: false });

        window.addEventListener('resize', () => {
            if (panel.dataset.describeVlmChatMoved === '1') keepFloatingPanelInViewport(panel, margin);
        });
    }

    function installDescribeFloatingResize(modal, panel) {
        const handle = panel?.querySelector?.('[data-describe-vlm-chat-resize]');
        if (!modal || !panel || !handle || handle.dataset.describeVlmFloatingResizeBound === '1') return;
        handle.dataset.describeVlmFloatingResizeBound = '1';

        const margin = 12;
        let resizeState = null;

        const onMove = (evt) => {
            if (!resizeState || evt.pointerId !== resizeState.pointerId) return;
            const dx = (evt.clientX ?? resizeState.startClientX) - resizeState.startClientX;
            const dy = (evt.clientY ?? resizeState.startClientY) - resizeState.startClientY;
            if (!resizeState.moved && Math.hypot(dx, dy) < 2) return;
            if (!resizeState.moved) {
                resizeState.moved = true;
                handle.classList.add('is-resizing');
                document.documentElement.classList.add('describe-vlm-chat-resizing');
                setImportantStyle(panel, 'transform', 'none');
                setImportantStyle(panel, 'left', `${Math.round(resizeState.left)}px`);
                setImportantStyle(panel, 'top', `${Math.round(resizeState.top)}px`);
                setImportantStyle(panel, 'right', 'auto');
                setImportantStyle(panel, 'bottom', 'auto');
            }
            const bounds = floatingResizeBoundsFrom(resizeState.left, resizeState.top, margin);
            applyFloatingPanelSize(panel, resizeState.width + dx, resizeState.height + dy, bounds);
            evt.preventDefault();
            evt.stopPropagation();
        };

        const onUp = (evt) => {
            if (!resizeState || (evt && evt.pointerId !== resizeState.pointerId)) return;
            const moved = resizeState.moved;
            resizeState = null;
            handle.classList.remove('is-resizing');
            document.documentElement.classList.remove('describe-vlm-chat-resizing');
            document.removeEventListener('pointermove', onMove, true);
            document.removeEventListener('pointerup', onUp, true);
            document.removeEventListener('pointercancel', onUp, true);
            if (moved) keepFloatingPanelInViewport(panel, margin);
            if (moved) saveFloatingPanelLayout(panel);
            evt?.preventDefault?.();
            evt?.stopPropagation?.();
        };

        handle.addEventListener('pointerdown', (evt) => {
            if (evt.button !== 0 || isFloatingModalHidden(modal)) return;
            const rect = panel.getBoundingClientRect();
            if (!rect.width || !rect.height) return;
            resizeState = {
                pointerId: evt.pointerId,
                startClientX: evt.clientX ?? 0,
                startClientY: evt.clientY ?? 0,
                left: rect.left,
                top: rect.top,
                width: rect.width,
                height: rect.height,
                moved: false
            };
            try { handle.setPointerCapture?.(evt.pointerId); } catch (err) {}
            document.addEventListener('pointermove', onMove, true);
            document.addEventListener('pointerup', onUp, true);
            document.addEventListener('pointercancel', onUp, true);
            evt.preventDefault();
            evt.stopPropagation();
        }, { passive: false });

        window.addEventListener('resize', () => {
            if (panel.dataset.describeVlmChatResized === '1' && !isFloatingModalHidden(modal)) {
                clampFloatingPanelSizeToViewport(panel, margin);
                keepFloatingPanelInViewport(panel, margin);
            }
        });
    }

    function installDescribeFloatingLayer(modal) {
        if (!modal) return modal;
        const host = ensureFloatingHost();
        if (modal.parentElement !== host) host.appendChild(modal);
        modal.classList.add('sai-floating-shell', 'modal', 'simpleai-floating-portal-node');
        modal.dataset.simpleaiFloatingFor = 'describe_vlm_chat_modal';

        const panel = modal.querySelector('.describe-vlm-chat-panel');
        if (panel) {
            panel.classList.add('sai-floating-card', 'modal-content', 'simpleai-resizable-popup');
            installDescribeFloatingDrag(modal, panel);
            installDescribeFloatingResize(modal, panel);
            if (!isFloatingModalHidden(modal)) {
                applySavedFloatingPanelLayout(panel);
            }
            if (panel.dataset.describeVlmChatResized === '1' && !isFloatingModalHidden(modal)) {
                clampFloatingPanelSizeToViewport(panel);
            }
            if ((panel.dataset.describeVlmChatMoved === '1' || panel.dataset.describeVlmChatResized === '1') && !isFloatingModalHidden(modal)) {
                keepFloatingPanelInViewport(panel);
            }
        }
        return modal;
    }

    function ensureModal() {
        let modal = document.getElementById('describe_vlm_chat_modal');
        if (modal) return installDescribeFloatingLayer(modal);
        modal = document.createElement('div');
        modal.id = 'describe_vlm_chat_modal';
        modal.className = 'describe-vlm-chat-modal';
        modal.hidden = true;
        modal.innerHTML = `
<div class="describe-vlm-chat-panel" role="dialog" aria-modal="true" aria-label="${escapeHtml(t('VLM/LLM AI chat', 'VLM/LLM AI对话'))}">
  <div class="describe-vlm-chat-head">
    <strong class="describe-vlm-chat-title"><i class="fa-solid fa-comments"></i><span class="describe-vlm-chat-title-text">${escapeHtml(t('VLM/LLM AI chat', 'VLM/LLM AI对话'))}</span></strong>
    <div class="describe-vlm-chat-model-pill" data-describe-vlm-chat-model aria-live="polite">
      <i class="fa-solid fa-microchip"></i>
      <span>${escapeHtml(t('Model', '模型'))}</span>
      <select data-describe-vlm-chat-model-select aria-label="${escapeHtml(t('Answering model', '当前应答模型'))}">
        <option value="">${escapeHtml(t('Detecting', '检测中'))}</option>
      </select>
      <b data-describe-vlm-chat-model-value hidden>${escapeHtml(t('Detecting', '检测中'))}</b>
    </div>
    <span class="describe-vlm-chat-head-actions">
      <button type="button" data-describe-vlm-chat-close title="${escapeHtml(t('Close', '关闭'))}" aria-label="${escapeHtml(t('Close', '关闭'))}"><i class="fa-solid fa-xmark"></i></button>
    </span>
  </div>
  <div class="describe-vlm-chat-controls">
    <label><span>${escapeHtml(t('Mode', '模式'))}</span><select data-describe-vlm-chat-mode aria-label="${escapeHtml(t('Chat Mode', '对话模式'))}">
      <option value="chat" ${state.chatMode === 'chat' ? 'selected' : ''}>${escapeHtml(t('Free Chat', '自由对话'))}</option>
      <option value="guide" ${state.chatMode === 'guide' ? 'selected' : ''}>${escapeHtml(t('Guide Mode', '向导模式'))}</option>
      <option value="prompt" ${state.chatMode === 'prompt' ? 'selected' : ''}>${escapeHtml(t('Prompt Assistant', '提示词助手'))}</option>
      <option value="raw" ${state.chatMode === 'raw' ? 'selected' : ''}>${escapeHtml(t('Raw Model', '原始模型'))}</option>
    </select></label>
    <label class="describe-vlm-chat-template-field"><span>${escapeHtml(t('Template', '模板'))}</span><select data-describe-vlm-chat-template aria-label="${escapeHtml(t('System Prompt Template', '系统提示词模板'))}">${renderSystemPromptTemplateOptions()}</select></label>
    <label class="describe-vlm-chat-system-field"><span>${escapeHtml(t('System Prompt', '系统提示词'))}</span><textarea data-describe-vlm-chat-system rows="2" placeholder="${escapeHtml(t('Optional custom system prompt...', '可选自定义 system prompt...'))}">${escapeHtml(state.customSystemPrompt)}</textarea></label>
    <div class="describe-vlm-chat-mode-hint" data-describe-vlm-chat-mode-hint>${escapeHtml(t('Free Chat may not know SimpAI main UI workflows. For feature recommendations, switch to Guide Mode.', '自由对话可能不了解 SimpAI 主界面功能；需要功能推荐时可切换到向导模式。'))}</div>
  </div>
  <div class="describe-vlm-chat-log" data-describe-vlm-chat-log></div>
  <div class="describe-vlm-chat-status" data-describe-vlm-chat-status></div>
  <div class="describe-vlm-chat-compose">
    <div class="describe-vlm-chat-compose-tools" aria-label="${escapeHtml(t('Chat tools', '对话工具'))}">
      <button type="button" data-describe-vlm-chat-import-prompt title="${escapeHtml(t('Import main prompt to input', '导入主提示词到输入框'))}" aria-label="${escapeHtml(t('Import main prompt to input', '导入主提示词到输入框'))}"><i class="fa-solid fa-file-import"></i></button>
      <button type="button" data-describe-vlm-chat-clear title="${escapeHtml(t('Clear chat', '清空对话'))}" aria-label="${escapeHtml(t('Clear chat', '清空对话'))}"><i class="fa-solid fa-broom"></i></button>
    </div>
    <label class="describe-vlm-chat-image-toggle"><input type="checkbox" data-describe-vlm-chat-use-image checked><span>${escapeHtml(t('Use image', '使用图片'))}</span></label>
    <label class="describe-vlm-chat-unload-toggle" title="${escapeHtml(t('Unload the local VLM/LLM model after each reply.', '每次回复后卸载本地 VLM/LLM 模型。'))}"><input type="checkbox" data-describe-vlm-chat-unload-after><span>${escapeHtml(t('Unload after reply', '回复后卸载模型'))}</span></label>
    <button type="button" data-describe-vlm-chat-pick-image title="${escapeHtml(t('Attach reference image', '添加引用图片'))}" aria-label="${escapeHtml(t('Attach reference image', '添加引用图片'))}"><i class="fa-solid fa-image"></i></button>
    <div class="describe-vlm-chat-attachments" data-describe-vlm-chat-attachments hidden></div>
    <textarea data-describe-vlm-chat-input rows="2" placeholder="${escapeHtml(chatInputPlaceholder(state.chatMode))}"></textarea>
    <button type="button" data-describe-vlm-chat-stop title="${escapeHtml(t('Stop reply', '停止回答'))}" aria-label="${escapeHtml(t('Stop reply', '停止回答'))}" hidden><i class="fa-solid fa-stop"></i></button>
    <button type="button" data-describe-vlm-chat-send title="${escapeHtml(t('Send', '发送'))}" aria-label="${escapeHtml(t('Send', '发送'))}"><i class="fa-solid fa-paper-plane"></i></button>
    <input type="file" accept="image/*" multiple data-describe-vlm-chat-file hidden>
  </div>
  <button type="button" class="describe-vlm-chat-resize-handle simpleai-popup-resize-handle" data-describe-vlm-chat-resize title="${escapeHtml(t('Resize window', '调整窗口大小'))}" aria-label="${escapeHtml(t('Resize window', '调整窗口大小'))}"></button>
</div>`;
        installDescribeFloatingLayer(modal);
        syncChatSettingsControls(modal);
        syncBusyControls(modal);
        renderMessages();
        renderPendingImages();
        ensureSystemPromptTemplates(modal).catch(() => {});
        return modal;
    }

    function openModal() {
        const modal = ensureModal();
        syncChatSettingsControls(modal);
        ensureSystemPromptTemplates(modal).catch(() => {});
        modal.hidden = false;
        installDescribeFloatingLayer(modal);
        document.documentElement.classList.add('describe-vlm-chat-open');
        window.requestAnimationFrame(() => {
            const panel = modal.querySelector('.describe-vlm-chat-panel');
            if (applySavedFloatingPanelLayout(panel)) return;
            if (panel?.dataset.describeVlmChatResized === '1') clampFloatingPanelSizeToViewport(panel);
            if (panel?.dataset.describeVlmChatMoved === '1' || panel?.dataset.describeVlmChatResized === '1') keepFloatingPanelInViewport(panel);
        });
        window.setTimeout(() => modal.querySelector('[data-describe-vlm-chat-input]')?.focus(), 40);
    }

    function closeModal() {
        const modal = ensureModal();
        modal.hidden = true;
        document.documentElement.classList.remove('describe-vlm-chat-open');
    }

    async function clearConversation() {
        const previousConversationId = state.conversationId;
        const previousRequestId = state.activeRequestId;
        state.requestToken += 1;
        state.busy = false;
        abortActiveChatRequest();
        state.messages = [];
        state.conversationId = uid('describe_vlm_chat');
        setStatus('');
        syncBusyControls(document.getElementById('describe_vlm_chat_modal'));
        renderMessages();
        notifyBackendChatCancel(previousConversationId, previousRequestId).catch(() => {});
        if (!previousConversationId) return;
        const response = await postJson('/describe-image/vlm-chat-clear', {
            conversation_id: previousConversationId,
            clear_context: true
        });
        if (!response?.ok) {
            setStatus(t('Chat cleared locally; backend context clear failed.', '已清空本地对话；后端上下文清理失败。'), true);
        }
    }

    function confirmClearConversation() {
        return window.confirm(t('Clear the current chat? This cannot be undone.', '确认清理当前对话？此操作无法撤销。'));
    }

    function positionOpenButton(host, textarea, anchorHost) {
        if (!host || !textarea || !anchorHost) return;
        const textareaBox = textarea.getBoundingClientRect();
        const anchorBox = anchorHost.getBoundingClientRect();
        if (!textareaBox.width || !textareaBox.height || !anchorBox.width || !anchorBox.height) return;
        const baseRight = Math.max(0, anchorBox.right - textareaBox.right);
        const baseY = Math.max(0, textareaBox.top - anchorBox.top + textareaBox.height / 2);
        host.style.setProperty('--describe-vlm-chat-button-base-right', `${baseRight}px`);
        host.style.setProperty('--describe-vlm-chat-button-base-y', `${baseY}px`);
    }

    function isCardOpenButton(host) {
        return !!(
            host?.classList?.contains('describe-vlm-chat-entry-card') ||
            host?.querySelector?.('.describe-vlm-chat-entry-wide')
        );
    }

    function anchorOpenButton() {
        const host = root().querySelector('#describe_vlm_chat_button');
        if (!host) return false;
        if (isCardOpenButton(host)) {
            host.classList.add('is-describe-chat-card');
            host.classList.remove('is-describe-prompt-anchored');
            host.style.removeProperty('--describe-vlm-chat-button-base-right');
            host.style.removeProperty('--describe-vlm-chat-button-base-y');
            root().querySelectorAll('#describe_prompt .describe-vlm-chat-anchor-host').forEach((node) => {
                node.classList.remove('describe-vlm-chat-anchor-host');
            });
            return true;
        }
        const promptHost = root().querySelector('#describe_prompt');
        if (!promptHost) return false;
        const textarea = promptHost.querySelector('textarea');
        const anchorHost = textarea?.parentElement || promptHost;
        if (host.parentElement !== anchorHost) {
            anchorHost.appendChild(host);
        }
        promptHost.querySelectorAll('.describe-vlm-chat-anchor-host').forEach((node) => {
            if (node !== anchorHost) node.classList.remove('describe-vlm-chat-anchor-host');
        });
        anchorHost.classList.add('describe-vlm-chat-anchor-host');
        host.classList.add('is-describe-prompt-anchored');
        positionOpenButton(host, textarea, anchorHost);
        return true;
    }

    function setStatus(message, isError) {
        const modal = ensureModal();
        const status = modal.querySelector('[data-describe-vlm-chat-status]');
        if (!status) return;
        status.classList.remove('is-actionable');
        status.textContent = message || '';
        status.classList.toggle('is-error', !!isError);
        if (!message) state.missingVlmModelRequest = null;
    }

    function syncBusyControls(modal) {
        const targetModal = modal || document.getElementById('describe_vlm_chat_modal');
        if (!targetModal) return;
        const send = targetModal.querySelector('[data-describe-vlm-chat-send]');
        const stop = targetModal.querySelector('[data-describe-vlm-chat-stop]');
        if (send) {
            send.disabled = !!state.busy;
            send.classList.toggle('is-busy', !!state.busy);
            send.setAttribute('aria-disabled', state.busy ? 'true' : 'false');
        }
        if (stop) {
            stop.hidden = !state.busy;
            stop.disabled = !state.busy;
            stop.setAttribute('aria-hidden', state.busy ? 'false' : 'true');
        }
    }

    function abortActiveChatRequest() {
        const controller = state.activeAbortController;
        state.activeAbortController = null;
        state.activeRequestId = '';
        try {
            controller?.abort?.();
        } catch (err) {}
    }

    function replacePendingAssistant(content) {
        const pendingIndex = state.messages.findIndex((item) => item.pending);
        const assistant = { role: 'assistant', content };
        if (pendingIndex >= 0) state.messages[pendingIndex] = assistant;
        else state.messages.push(assistant);
    }

    async function notifyBackendChatCancel(conversationId, requestId) {
        if (!conversationId && !requestId) return;
        await postJson('/describe-image/vlm-chat-cancel', {
            conversation_id: conversationId || '',
            request_id: requestId || ''
        });
    }

    async function stopCurrentChatReply(options = {}) {
        if (!state.busy && !state.activeAbortController && !state.activeRequestId) return false;
        const conversationId = state.conversationId;
        const requestId = state.activeRequestId;
        state.requestToken += 1;
        state.busy = false;
        abortActiveChatRequest();
        if (!options?.silent) {
            replacePendingAssistant(t('Stopped.', '已停止。'));
            setStatus(t('Reply stopped.', '已停止当前回复。'));
        }
        syncBusyControls(document.getElementById('describe_vlm_chat_modal'));
        renderMessages();
        notifyBackendChatCancel(conversationId, requestId).catch(() => {});
        return true;
    }

    function imageSummary(image) {
        return {
            name: image?.name || 'image',
            width: image?.width || null,
            height: image?.height || null,
            thumb: image?.thumb || ONE_PIXEL_IMAGE,
            placeholder: true
        };
    }

    function renderImageChips(images, removable) {
        const rows = Array.isArray(images) ? images : [];
        if (!rows.length) return '';
        return `<div class="describe-vlm-chat-image-chips">${rows.map((image, index) => {
            const size = image?.width && image?.height ? ` ${Number(image.width)}x${Number(image.height)}` : '';
            const label = `${image?.name || t('Image', '图片')}${size}`;
            return `<span class="describe-vlm-chat-image-chip">
  <img src="${escapeHtml(image?.thumb || ONE_PIXEL_IMAGE)}" alt="">
  <span>${escapeHtml(label)}</span>
  ${removable ? `<button type="button" data-describe-vlm-chat-remove-image="${index}" title="${escapeHtml(t('Remove', '移除'))}" aria-label="${escapeHtml(t('Remove', '移除'))}"><i class="fa-solid fa-xmark"></i></button>` : ''}
</span>`;
        }).join('')}</div>`;
    }

    function chatMessageText(message) {
        return historyTextForMessage(message);
    }

    function focusChatInput(selectText = false) {
        const input = ensureModal().querySelector('[data-describe-vlm-chat-input]');
        if (!input) return false;
        input.focus();
        const end = String(input.value || '').length;
        try {
            input.setSelectionRange(selectText ? 0 : end, end);
        } catch (err) {
            // Some embedded browsers can reject selection while the textarea is rerendering.
        }
        return true;
    }

    function setChatInputValue(value, selectText = false) {
        const input = ensureModal().querySelector('[data-describe-vlm-chat-input]');
        if (!input) return false;
        input.value = String(value || '');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        focusChatInput(selectText);
        return true;
    }

    function importMainPromptToChatInput() {
        const prompt = readComponentValue('positive_prompt').trim();
        if (!prompt) {
            setStatus(t('Main prompt is empty.', '主提示词为空。'), true);
            return;
        }
        const modal = ensureModal();
        const input = modal.querySelector('[data-describe-vlm-chat-input]');
        const current = String(input?.value || '').trimEnd();
        const label = t('Current main prompt', '当前主提示词');
        const block = `${label}:\n${prompt}`;
        const next = current ? `${current}\n\n${block}` : block;
        if (setChatInputValue(next, false)) {
            setStatus(t('Main prompt imported to input.', '主提示词已导入输入框。'));
        }
    }

    function resetConversationAfterContextEdit() {
        const previousConversationId = state.conversationId;
        state.requestToken += 1;
        state.busy = false;
        state.conversationId = uid('describe_vlm_chat');
        if (previousConversationId) {
            postJson('/describe-image/vlm-chat-clear', {
                conversation_id: previousConversationId,
                clear_context: true
            }).catch(() => {});
        }
    }

    function copyChatMessage(messageIndex) {
        const message = state.messages[Number(messageIndex)];
        const text = chatMessageText(message);
        if (!text.trim()) {
            setStatus(t('No message text to copy.', '没有可复制的消息文本。'), true);
            return;
        }
        navigator.clipboard?.writeText(text).then(
            () => setStatus(t('Message copied.', '消息已复制。')),
            () => setStatus(t('Copy failed.', '复制失败。'), true)
        );
    }

    function quoteChatMessage(messageIndex) {
        const message = state.messages[Number(messageIndex)];
        const text = chatMessageText(message);
        if (!text.trim()) {
            setStatus(t('No message text to quote.', '没有可引用的消息文本。'), true);
            return;
        }
        const modal = ensureModal();
        const input = modal.querySelector('[data-describe-vlm-chat-input]');
        const current = String(input?.value || '');
        const quote = `> ${text.replace(/\n/g, '\n> ')}\n\n`;
        if (setChatInputValue(`${quote}${current}`, false)) {
            setStatus(t('Message quoted to input.', '已引用到输入框。'));
        }
    }

    function rollbackChatToMessage(messageIndex) {
        const index = Number(messageIndex);
        if (!Number.isInteger(index) || index < 0 || index >= state.messages.length) return;
        const message = state.messages[index];
        if (message?.pending || state.busy) {
            setStatus(t('Wait for the active response before editing context.', '请等待当前回复结束后再编辑上下文。'), true);
            return;
        }
        const draft = chatMessageText(message);
        state.messages = state.messages.slice(0, index).filter((item) => !item?.pending);
        resetConversationAfterContextEdit();
        setStatus(t('Message moved back to input.', '消息已回到输入框。'));
        renderMessages();
        setChatInputValue(draft, true);
    }

    function deleteChatMessage(messageIndex) {
        const index = Number(messageIndex);
        if (!Number.isInteger(index) || index < 0 || index >= state.messages.length) return;
        if (state.messages[index]?.pending || state.busy) {
            setStatus(t('Wait for the active response before editing context.', '请等待当前回复结束后再编辑上下文。'), true);
            return;
        }
        state.messages.splice(index, 1);
        resetConversationAfterContextEdit();
        setStatus(t('Message deleted from context.', '消息已从上下文删除。'));
        renderMessages();
    }

    function renderPendingImages() {
        const modal = ensureModal();
        const tray = modal.querySelector('[data-describe-vlm-chat-attachments]');
        if (!tray) return;
        if (!state.pendingImages.length) {
            tray.hidden = true;
            tray.innerHTML = '';
            return;
        }
        tray.hidden = false;
        tray.innerHTML = renderImageChips(state.pendingImages.map(imageSummary), true);
    }

    function renderMessages() {
        const modal = ensureModal();
        const log = modal.querySelector('[data-describe-vlm-chat-log]');
        if (!log) return;
        syncBusyControls(modal);
        if (!state.messages.length) {
            log.innerHTML = `<div class="describe-vlm-chat-empty">${escapeHtml(t('No chat yet.', '暂无对话。'))}</div>`;
            return;
        }
        log.innerHTML = state.messages.map((message, messageIndex) => {
            const role = message.role === 'assistant' ? 'assistant' : 'user';
            const pending = !!message.pending;
            const actions = Array.isArray(message.actions) ? message.actions : [];
            const actionHtml = actions.length && !pending ? `<div class="describe-vlm-chat-actions">${actions.map((action, actionIndex) => {
                const promptText = String(action?.prompt || '').trim();
                if (!promptText) return '';
                const actionRef = `${messageIndex}:${actionIndex}`;
                const previewTitle = localText('Prepared prompt', '整理出的提示词');
                const setLabel = localText('Set', '写入');
                const setTitle = localText('Set main prompt', '写入主提示词');
                const appendLabel = localText('Append', '追加');
                const appendTitle = localText('Append to main prompt', '追加到主提示词');
                const copyLabel = localText('Copy', '复制');
                const copyTitle = localText('Copy prompt', '复制提示词');
                return `<div class="describe-vlm-chat-action-card">
  <div class="describe-vlm-chat-prompt-preview-label">${escapeHtml(previewTitle)}</div>
  <pre class="describe-vlm-chat-prompt-preview">${escapeHtml(promptText)}</pre>
  <div class="describe-vlm-chat-action-buttons">
    <button type="button" data-describe-vlm-chat-apply="${escapeHtml(actionRef)}" title="${escapeHtml(setTitle)}" aria-label="${escapeHtml(setTitle)}"><i class="fa-solid fa-arrow-right-to-bracket"></i><span>${escapeHtml(setLabel)}</span></button>
    <button type="button" data-describe-vlm-chat-append="${escapeHtml(actionRef)}" title="${escapeHtml(appendTitle)}" aria-label="${escapeHtml(appendTitle)}"><i class="fa-solid fa-plus"></i><span>${escapeHtml(appendLabel)}</span></button>
    <button type="button" data-describe-vlm-chat-copy="${escapeHtml(actionRef)}" title="${escapeHtml(copyTitle)}" aria-label="${escapeHtml(copyTitle)}"><i class="fa-solid fa-copy"></i><span>${escapeHtml(copyLabel)}</span></button>
  </div>
</div>`;
            }).join('')}</div>` : '';
            const label = role === 'assistant' ? t('Assistant', '助手') : t('You', '你');
            return `<div class="describe-vlm-chat-msg is-${role} ${pending ? 'is-pending' : ''}" data-describe-vlm-chat-message="${messageIndex}">
  <div class="describe-vlm-chat-msg-head"><b>${escapeHtml(label)}</b><span>
    <button type="button" data-describe-vlm-chat-copy-message="${messageIndex}" title="${escapeHtml(t('Copy message', '复制消息'))}" aria-label="${escapeHtml(t('Copy message', '复制消息'))}"><i class="fa-solid fa-copy"></i></button>
    <button type="button" data-describe-vlm-chat-quote="${messageIndex}" title="${escapeHtml(t('Quote to input', '引用到输入'))}" aria-label="${escapeHtml(t('Quote to input', '引用到输入'))}"><i class="fa-solid fa-reply"></i></button>
    <button type="button" data-describe-vlm-chat-rollback="${messageIndex}" title="${escapeHtml(t('Move this message back to input', '把这条消息放回输入框'))}" aria-label="${escapeHtml(t('Move this message back to input', '把这条消息放回输入框'))}"><i class="fa-solid fa-clock-rotate-left"></i></button>
    <button type="button" class="is-danger" data-describe-vlm-chat-delete="${messageIndex}" title="${escapeHtml(t('Delete this message from context', '从上下文删除此消息'))}" aria-label="${escapeHtml(t('Delete this message from context', '从上下文删除此消息'))}"><i class="fa-solid fa-trash"></i></button>
  </span></div>
  <p>${escapeHtml(message.content || '')}</p>
  ${renderImageChips(message.images, false)}
  ${actionHtml}
</div>`;
        }).join('');
        log.scrollTop = log.scrollHeight;
    }

    function resetConversationForImage(imageKey) {
        const key = String(imageKey || '');
        if (state.lastImageKey && state.lastImageKey !== key) {
            state.messages = [];
            state.conversationId = '';
        }
        state.lastImageKey = key;
    }

    function historyTextForMessage(message) {
        let content = String(message?.content || '').trim();
        const actionPrompts = Array.isArray(message?.actions)
            ? message.actions.map((action) => String(action?.prompt || '').trim()).filter(Boolean)
            : [];
        if (actionPrompts.length) {
            content = `${content}${content ? '\n' : ''}${localText('Prepared prompt', '整理出的提示词')}:\n${actionPrompts.join('\n\n')}`.trim();
        }
        const imageCount = Number(message?.image_count || (Array.isArray(message?.images) ? message.images.length : 0) || 0);
        if (imageCount > 0) {
            const placeholder = `[${imageCount} previous image reference(s) retained as 1x1 placeholder; full image bytes omitted.]`;
            content = `${content}${content ? '\n' : ''}${placeholder}`.trim();
        }
        return content;
    }

    function buildRollingHistory(limit = MAX_HISTORY_TURNS, budget = HISTORY_BUDGET) {
        const selected = [];
        let used = 0;
        let omitted = 0;
        const source = state.messages.filter((item) => !item.pending);
        for (let i = source.length - 1; i >= 0; i -= 1) {
            const message = source[i];
            let content = historyTextForMessage(message);
            if (!content) {
                omitted += 1;
                continue;
            }
            const maxOne = Math.max(500, Math.min(1800, Math.floor(budget / 3)));
            if (content.length > maxOne) content = content.slice(-maxOne).trimStart();
            const role = message.role === 'assistant' ? 'assistant' : message.role === 'system' ? 'system' : 'user';
            const cost = role.length + content.length + 16;
            if (selected.length >= limit || (selected.length && used + cost > budget)) {
                omitted += 1;
                continue;
            }
            selected.push({ role, content, image_count: Number(message.image_count || 0) || 0 });
            used += cost;
        }
        selected.reverse();
        return { messages: selected, omitted, chars: used, budget };
    }

    async function addPendingImageFiles(files) {
        const imageFiles = Array.from(files || []).filter((file) => /^image\//i.test(file.type || ''));
        if (!imageFiles.length) return;
        setStatus(t('Reading image...', '正在读取图片...'));
        for (const file of imageFiles.slice(0, MAX_ATTACHMENTS)) {
            try {
                const payload = await fileToImagePayload(file);
                state.pendingImages.push(payload);
            } catch (err) {
                setStatus(t('Image read failed.', '读取图片失败。'), true);
            }
        }
        if (state.pendingImages.length > MAX_ATTACHMENTS) {
            state.pendingImages = state.pendingImages.slice(-MAX_ATTACHMENTS);
        }
        renderPendingImages();
        setStatus(t('Reference image attached.', '引用图片已添加。'));
    }

    function collectClipboardImageFiles(dataTransfer) {
        const files = Array.from(dataTransfer?.files || []).filter((file) => /^image\//i.test(file.type || ''));
        if (files.length) return files;
        return Array.from(dataTransfer?.items || [])
            .filter((item) => item.kind === 'file' && /^image\//i.test(item.type || ''))
            .map((item) => item.getAsFile())
            .filter(Boolean);
    }

    function firstUriFromList(text) {
        return String(text || '').split(/\r?\n/).map((line) => line.trim()).find((line) => line && !line.startsWith('#')) || '';
    }

    function firstHtmlImageSrc(html) {
        if (!html) return '';
        try {
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const src = doc.querySelector('img[src]')?.getAttribute('src') || '';
            if (src) return src;
        } catch (err) {}
        const match = String(html).match(/<img\b[^>]*\bsrc=["']?([^"'\s>]+)/i);
        return match ? match[1] : '';
    }

    function base64UrlDecodeUtf8(value) {
        const text = String(value || '');
        if (!text) return '';
        const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - text.length % 4) % 4);
        try {
            const binary = atob(padded);
            const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
            if (window.TextDecoder) return new TextDecoder('utf-8').decode(bytes);
            return decodeURIComponent(Array.from(bytes, (byte) => `%${byte.toString(16).padStart(2, '0')}`).join(''));
        } catch (err) {
            return '';
        }
    }

    function galleryOriginalSource(source) {
        try {
            const url = new URL(source, document.baseURI);
            const fileName = decodeURIComponent(url.pathname.split('/').filter(Boolean).pop() || '');
            const match = fileName.match(/^simpai_gprev__([A-Za-z0-9_-]+)__[0-9a-f]{16}\.jpg$/);
            if (!match) return source;
            const originalPath = base64UrlDecodeUtf8(match[1]);
            if (!originalPath) return source;
            const route = '/simpleai/gallery-preview/';
            const routeIndex = url.pathname.indexOf(route);
            const basePath = routeIndex >= 0 ? url.pathname.slice(0, routeIndex) : '';
            const encodedPath = encodeURI(String(originalPath).replace(/\\/g, '/')).replace(/\?/g, '%3F').replace(/#/g, '%23');
            return `${url.origin}${basePath}/gradio_api/file=${encodedPath}`;
        } catch (err) {
            return source;
        }
    }

    function normalizeImageDropSource(source) {
        const value = String(source || '').trim();
        if (!value) return '';
        let normalized = value;
        try {
            normalized = new URL(value, document.baseURI).href;
        } catch (err) {}
        return galleryOriginalSource(normalized);
    }

    function firstImageDropUrl(dataTransfer) {
        if (!dataTransfer || typeof dataTransfer.getData !== 'function') return '';
        const custom = normalizeImageDropSource(dataTransfer.getData('application/x-simpleai-gallery-original-url'));
        if (custom) return custom;
        const uri = normalizeImageDropSource(firstUriFromList(dataTransfer.getData('text/uri-list')));
        if (uri) return uri;
        const htmlSrc = normalizeImageDropSource(firstHtmlImageSrc(dataTransfer.getData('text/html')));
        if (htmlSrc) return htmlSrc;
        return normalizeImageDropSource(dataTransfer.getData('text/plain'));
    }

    async function imageFileFromDropUrl(source) {
        if (!source) return null;
        try {
            const response = await fetch(source, { credentials: 'same-origin' });
            if (!response.ok) return null;
            const blob = await response.blob();
            const mime = blob.type || 'image/png';
            if (mime && !mime.toLowerCase().startsWith('image/')) return null;
            const rawExt = (mime.split('/')[1] || 'png').split(';')[0].replace('svg+xml', 'svg');
            const ext = rawExt === 'jpeg' ? 'jpg' : rawExt;
            return new File([blob], `dropped-image.${ext}`, { type: mime });
        } catch (err) {
            return null;
        }
    }

    async function collectDroppedImageFiles(dataTransfer) {
        const url = firstImageDropUrl(dataTransfer);
        if (url) {
            const file = await imageFileFromDropUrl(url);
            if (file) return [file];
        }
        return collectClipboardImageFiles(dataTransfer);
    }

    function modalIsOpen() {
        const modal = document.getElementById('describe_vlm_chat_modal');
        return !!modal && !modal.hidden;
    }

    function eventInsideModal(evt) {
        const modal = document.getElementById('describe_vlm_chat_modal');
        return !!modal && (modal.contains(evt.target) || modal.contains(document.activeElement));
    }

    function eventTargetElement(target) {
        return target instanceof Element ? target : target?.parentElement || null;
    }

    function targetInsideChatPanel(target, modal = document.getElementById('describe_vlm_chat_modal')) {
        const panel = modal?.querySelector?.('.describe-vlm-chat-panel');
        const element = eventTargetElement(target);
        return !!panel && !!element && panel.contains(element);
    }

    function targetIsChatBackdrop(target, modal = document.getElementById('describe_vlm_chat_modal')) {
        return !!modal && target === modal;
    }

    function handleModalPointerDown(evt) {
        const modal = document.getElementById('describe_vlm_chat_modal');
        modalBackdropPointerStarted = !!modal && !modal.hidden && targetIsChatBackdrop(evt.target, modal);
    }

    function handleModalPointerUp(evt) {
        const modal = document.getElementById('describe_vlm_chat_modal');
        const shouldClose = modalBackdropPointerStarted && !!modal && !modal.hidden && targetIsChatBackdrop(evt.target, modal);
        modalBackdropPointerStarted = false;
        if (!shouldClose) return;
        evt.preventDefault();
        evt.stopPropagation();
        closeModal();
    }

    function resetModalPointerState() {
        modalBackdropPointerStarted = false;
    }

    function isWheelScrollable(node) {
        if (!(node instanceof Element)) return false;
        const style = window.getComputedStyle(node);
        const canOverflowY = /auto|scroll|overlay/i.test(style.overflowY || '');
        const canOverflowX = /auto|scroll|overlay/i.test(style.overflowX || '');
        return (canOverflowY && node.scrollHeight > node.clientHeight + 1) ||
            (canOverflowX && node.scrollWidth > node.clientWidth + 1);
    }

    function canScrollWithWheel(node, evt) {
        const deltaY = Number(evt.deltaY || 0);
        const deltaX = Number(evt.deltaX || 0);
        const canScrollDown = deltaY > 0 && node.scrollTop + node.clientHeight < node.scrollHeight - 1;
        const canScrollUp = deltaY < 0 && node.scrollTop > 0;
        const canScrollRight = deltaX > 0 && node.scrollLeft + node.clientWidth < node.scrollWidth - 1;
        const canScrollLeft = deltaX < 0 && node.scrollLeft > 0;
        return canScrollDown || canScrollUp || canScrollRight || canScrollLeft;
    }

    function closestScrollableForWheel(target, modal, evt) {
        const panel = modal?.querySelector?.('.describe-vlm-chat-panel');
        let node = eventTargetElement(target);
        while (node && panel?.contains(node)) {
            if (isWheelScrollable(node) && canScrollWithWheel(node, evt)) return node;
            if (node === panel) break;
            node = node.parentElement;
        }
        return null;
    }

    function containModalWheel(evt) {
        const modal = document.getElementById('describe_vlm_chat_modal');
        if (!modal || modal.hidden) return;
        const insideModal = modal.contains(evt.target);
        const insidePanel = insideModal && targetInsideChatPanel(evt.target, modal);
        const scroller = insidePanel ? closestScrollableForWheel(evt.target, modal, evt) : null;
        if (!insidePanel || !scroller) {
            evt.preventDefault();
        }
        evt.stopPropagation();
    }

    async function sendMessage() {
        if (state.busy) return;
        const requestToken = state.requestToken + 1;
        state.requestToken = requestToken;
        const modal = ensureModal();
        const input = modal.querySelector('[data-describe-vlm-chat-input]');
        const selectedMode = normalizeChatMode(modal.querySelector('[data-describe-vlm-chat-mode]')?.value || state.chatMode);
        const customSystemPrompt = modal.querySelector('[data-describe-vlm-chat-system]')?.value ?? state.customSystemPrompt;
        const selectedTemplateId = modal.querySelector('[data-describe-vlm-chat-template]')?.value || selectedSystemPromptTemplateIdForContent(customSystemPrompt);
        state.chatMode = selectedMode;
        state.customSystemPrompt = customSystemPrompt;
        state.systemPromptTemplateId = selectedTemplateId && (!state.systemPromptTemplatesLoaded || selectedSystemPromptTemplateIdForContent(customSystemPrompt) === selectedTemplateId) ? selectedTemplateId : '';
        saveChatSettings();
        const typed = String(input?.value || '').trim();
        const pendingImages = state.pendingImages.slice();
        if (!typed && !pendingImages.length) return;
        const version = readSelectedVlmVersion();
        updateAnswerModelIndicator(modal);
        const modelReady = await ensureSelectedVlmModelReady(version);
        if (requestToken !== state.requestToken) return;
        if (!modelReady) return;

        state.busy = true;
        syncBusyControls(modal);
        setStatus('');
        if (input) input.value = '';
        state.pendingImages = [];
        renderPendingImages();

        const message = typed || defaultMessageForMode(selectedMode);
        const includeCurrentPrompt = shouldSendCurrentPromptToVlm(selectedMode, message);
        const imageElement = state.useImage ? currentImageElement() : null;
        const imageKey = imageElement ? (imageElement.currentSrc || imageElement.src || '') : '';
        resetConversationForImage(imageKey);
        const history = buildRollingHistory(MAX_HISTORY_TURNS, HISTORY_BUDGET);
        const fullHistory = buildRollingHistory(32, FULL_HISTORY_BUDGET);

        const images = [];
        try {
            if (state.useImage && imageKey) {
                const currentImage = await currentImagePayload();
                if (currentImage) images.push(currentImage);
            }
        } catch (err) {
            setStatus(t('Image read failed; sending text only.', '读取图片失败，将仅发送文本。'), true);
        }
        for (const image of pendingImages) {
            if (images.length >= MAX_ATTACHMENTS) break;
            if (image?.data_url) images.push(image);
        }
        if (requestToken !== state.requestToken) return;

        state.messages.push({
            role: 'user',
            content: message,
            image_count: images.length,
            images: images.map(imageSummary)
        });
        state.messages.push({ role: 'assistant', content: t('Thinking', '思考中'), pending: true });
        renderMessages();

        const requestId = uid('describe_vlm_chat_req');
        const abortController = new AbortController();
        state.activeRequestId = requestId;
        state.activeAbortController = abortController;
        const payload = {
            message,
            current_prompt: includeCurrentPrompt ? readComponentValue('positive_prompt') : '',
            include_current_prompt: includeCurrentPrompt,
            conversation_id: ensureConversationId(),
            request_id: requestId,
            history: history.messages,
            history_full: fullHistory.messages,
            context: {
                omitted: history.omitted,
                chars: history.chars,
                budget: history.budget
            },
            image: images[0] || null,
            images,
            version,
            custom_api: readDescribeCustomApi(version),
            chat_mode: selectedMode,
            user_system_prompt: customSystemPrompt,
            system_prompt_template_id: state.systemPromptTemplateId,
            unload_after_chat: !!state.unloadAfterChat,
            free_after: !!state.unloadAfterChat,
            prompt_options: readDescribePromptOptions(),
            lang: getUiLang(window.simpleaiTopbarSystemParams || {})
        };
        const response = await postJson('/describe-image/vlm-chat-run', payload, { signal: abortController.signal });
        if (state.activeRequestId === requestId) {
            state.activeRequestId = '';
            state.activeAbortController = null;
        }
        if (requestToken !== state.requestToken) return;
        if (response?.aborted) {
            state.busy = false;
            replacePendingAssistant(t('Stopped.', '已停止。'));
            renderMessages();
            setStatus(t('Reply stopped.', '已停止当前回复。'));
            return;
        }
        const pendingIndex = state.messages.findIndex((item) => item.pending);
        const reply = response?.ok
            ? (response.text || t('Done.', '完成。'))
            : (response?.details || response?.error || t('VLM/LLM AI chat failed.', 'VLM/LLM AI对话失败。'));
        const assistant = {
            role: 'assistant',
            content: reply,
            actions: response?.ok && Array.isArray(response.limited_actions) ? response.limited_actions : []
        };
        if (pendingIndex >= 0) state.messages[pendingIndex] = assistant;
        else state.messages.push(assistant);
        if (response?.conversation_id) state.conversationId = response.conversation_id;
        state.busy = false;
        renderMessages();
        if (!response?.ok) setStatus(reply, true);
    }

    function actionFromRef(ref) {
        const [messageIndex, actionIndex] = String(ref || '').split(':').map((part) => Number(part));
        const action = state.messages[messageIndex]?.actions?.[actionIndex];
        return action && typeof action === 'object' ? action : null;
    }

    function promptValueForAction(action) {
        const promptText = String(action?.prompt || '').trim();
        if (!promptText) return '';
        const current = readComponentValue('positive_prompt').trim();
        return action.type === 'append_prompt'
            ? (current ? `${current}${current.includes('\n') || promptText.includes('\n') ? '\n' : ', '}${promptText}` : promptText)
            : promptText;
    }

    function optimisticPrompt(action) {
        const next = promptValueForAction(action);
        if (!next) return '';
        setComponentValue('positive_prompt', next);
        return next;
    }

    function applyPromptAction(action) {
        if (!action?.prompt) return;
        const nextPrompt = optimisticPrompt(action);
        setComponentValue('describe_vlm_chat_prompt_bridge', JSON.stringify({ type: 'set_prompt', prompt: nextPrompt }));
        clickComponentButton('describe_vlm_chat_apply_prompt_btn');
        setStatus(t('Prompt updated.', '提示词已更新。'));
    }

    document.addEventListener('click', (evt) => {
        const openButton = evt.target.closest?.('#describe_vlm_chat_button, #describe_vlm_chat_button button, .describe-vlm-chat-entry');
        if (openButton) {
            evt.preventDefault();
            openModal();
            return;
        }
        const modal = document.getElementById('describe_vlm_chat_modal');
        if (!modal || modal.hidden) return;
        if (evt.target.closest('[data-describe-vlm-chat-close]')) {
            closeModal();
            return;
        }
        if (evt.target.closest('[data-describe-vlm-chat-clear]')) {
            if (confirmClearConversation()) clearConversation();
            return;
        }
        if (evt.target.closest('[data-describe-vlm-chat-import-prompt]')) {
            importMainPromptToChatInput();
            return;
        }
        if (evt.target.closest('[data-describe-vlm-chat-pick-image]')) {
            modal.querySelector('[data-describe-vlm-chat-file]')?.click();
            return;
        }
        const removeImage = evt.target.closest('[data-describe-vlm-chat-remove-image]');
        if (removeImage) {
            const index = Number(removeImage.getAttribute('data-describe-vlm-chat-remove-image'));
            if (Number.isFinite(index)) state.pendingImages.splice(index, 1);
            renderPendingImages();
            return;
        }
        if (evt.target.closest('[data-describe-vlm-chat-stop]')) {
            stopCurrentChatReply();
            return;
        }
        const sendButton = evt.target.closest('[data-describe-vlm-chat-send]');
        if (sendButton) {
            if (!sendButton.disabled) sendMessage();
            return;
        }
        if (evt.target.closest('[data-describe-vlm-chat-download-models]')) {
            const request = state.missingVlmModelRequest || {};
            if (!triggerVlmMissingModelPopup(request.version || readSelectedVlmVersion(), request.customApi || readDescribeCustomApi(readSelectedVlmVersion()))) {
                setStatus(t('Download panel is unavailable. Use the model selector status or reload the page.', '下载面板暂不可用，请通过模型状态入口处理，或刷新页面。'), true);
            }
            return;
        }
        const copyMessage = evt.target.closest('[data-describe-vlm-chat-copy-message]');
        if (copyMessage) {
            copyChatMessage(copyMessage.getAttribute('data-describe-vlm-chat-copy-message'));
            return;
        }
        const quoteMessage = evt.target.closest('[data-describe-vlm-chat-quote]');
        if (quoteMessage) {
            quoteChatMessage(quoteMessage.getAttribute('data-describe-vlm-chat-quote'));
            return;
        }
        const rollbackMessage = evt.target.closest('[data-describe-vlm-chat-rollback]');
        if (rollbackMessage) {
            rollbackChatToMessage(rollbackMessage.getAttribute('data-describe-vlm-chat-rollback'));
            return;
        }
        const deleteMessage = evt.target.closest('[data-describe-vlm-chat-delete]');
        if (deleteMessage) {
            deleteChatMessage(deleteMessage.getAttribute('data-describe-vlm-chat-delete'));
            return;
        }
        const apply = evt.target.closest('[data-describe-vlm-chat-apply]');
        if (apply) {
            const action = Object.assign({}, actionFromRef(apply.getAttribute('data-describe-vlm-chat-apply')) || {}, { type: 'set_prompt' });
            applyPromptAction(action);
            return;
        }
        const append = evt.target.closest('[data-describe-vlm-chat-append]');
        if (append) {
            const action = Object.assign({}, actionFromRef(append.getAttribute('data-describe-vlm-chat-append')) || {}, { type: 'append_prompt' });
            applyPromptAction(action);
            return;
        }
        const copy = evt.target.closest('[data-describe-vlm-chat-copy]');
        if (copy) {
            const action = actionFromRef(copy.getAttribute('data-describe-vlm-chat-copy'));
            if (action?.prompt) navigator.clipboard?.writeText(action.prompt).catch(() => {});
            setStatus(t('Prompt copied.', '提示词已复制。'));
        }
    });

    document.addEventListener('change', (evt) => {
        if (evt.target?.matches?.('[data-describe-vlm-chat-model-select]')) {
            setDescribeVlmVersionFromHeader(evt.target.value);
            return;
        }
        if (evt.target?.matches?.('[data-describe-vlm-chat-mode]')) {
            state.chatMode = normalizeChatMode(evt.target.value);
            saveChatSettings();
            syncChatSettingsControls(document.getElementById('describe_vlm_chat_modal'));
        }
        if (evt.target?.matches?.('[data-describe-vlm-chat-template]')) {
            applySystemPromptTemplate(evt.target.value, document.getElementById('describe_vlm_chat_modal'));
        }
        if (evt.target?.matches?.('[data-describe-vlm-chat-use-image]')) {
            state.useImage = !!evt.target.checked;
        }
        if (evt.target?.matches?.('[data-describe-vlm-chat-unload-after]')) {
            state.unloadAfterChat = !!evt.target.checked;
            saveChatSettings();
        }
        if (evt.target?.matches?.('[data-describe-vlm-chat-file]')) {
            addPendingImageFiles(evt.target.files || []);
            evt.target.value = '';
        }
        if (evt.target?.closest?.('#describe_vlm_model_dropdown, #describe_vlm_model, #describe_vlm_custom_panel')) {
            updateAnswerModelIndicator();
        }
    });

    document.addEventListener('input', (evt) => {
        if (evt.target?.matches?.('[data-describe-vlm-chat-system]')) {
            state.customSystemPrompt = evt.target.value || '';
            state.systemPromptTemplateId = selectedSystemPromptTemplateIdForContent(state.customSystemPrompt);
            syncSystemPromptTemplateControls(document.getElementById('describe_vlm_chat_modal'));
            saveChatSettings();
        }
        if (evt.target?.closest?.('#describe_vlm_model_dropdown, #describe_vlm_model, #describe_vlm_custom_panel')) {
            updateAnswerModelIndicator();
        }
    });

    document.addEventListener('pointerdown', handleModalPointerDown, true);
    document.addEventListener('pointerup', handleModalPointerUp, true);
    document.addEventListener('pointercancel', resetModalPointerState, true);
    document.addEventListener('wheel', containModalWheel, { capture: true, passive: false });

    document.addEventListener('paste', (evt) => {
        if (!modalIsOpen() || !eventInsideModal(evt)) return;
        if (evt.target?.closest?.('[data-describe-vlm-chat-system]')) return;
        const files = collectClipboardImageFiles(evt.clipboardData);
        if (!files.length) return;
        const text = evt.clipboardData?.getData?.('text/plain') || '';
        if (!text) evt.preventDefault();
        addPendingImageFiles(files);
    });

    document.addEventListener('dragover', (evt) => {
        if (!modalIsOpen() || !eventInsideModal(evt)) return;
        const hasImage = collectClipboardImageFiles(evt.dataTransfer).length > 0 || !!firstImageDropUrl(evt.dataTransfer);
        if (!hasImage) return;
        evt.preventDefault();
        document.getElementById('describe_vlm_chat_modal')?.classList.add('is-drag-over');
    });

    document.addEventListener('dragleave', () => {
        document.getElementById('describe_vlm_chat_modal')?.classList.remove('is-drag-over');
    });

    document.addEventListener('drop', async (evt) => {
        if (!modalIsOpen() || !eventInsideModal(evt)) return;
        const files = await collectDroppedImageFiles(evt.dataTransfer);
        if (!files.length) return;
        evt.preventDefault();
        document.getElementById('describe_vlm_chat_modal')?.classList.remove('is-drag-over');
        addPendingImageFiles(files);
    });

    document.addEventListener('keydown', (evt) => {
        const input = evt.target?.closest?.('[data-describe-vlm-chat-input]');
        if (!input) return;
        if (evt.key === 'Enter' && !evt.shiftKey) {
            evt.preventDefault();
            sendMessage();
        }
        if (evt.key === 'Escape') closeModal();
    });

    function labelOpenButton() {
        anchorOpenButton();
        const host = root().querySelector('#describe_vlm_chat_button');
        const button = host?.querySelector?.('button') || host;
        if (!button) return;
        const label = t('VLM/LLM AI chat', 'VLM/LLM AI对话');
        button.setAttribute('title', label);
        button.setAttribute('aria-label', label);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', labelOpenButton);
    } else {
        labelOpenButton();
    }
    try {
        let anchorPending = 0;
        const scheduleAnchor = () => {
            if (anchorPending) return;
            anchorPending = window.setTimeout(() => {
                anchorPending = 0;
                labelOpenButton();
                updateAnswerModelIndicator();
            }, 80);
        };
        new MutationObserver(scheduleAnchor).observe(document.body, { childList: true, subtree: true });
        window.addEventListener('resize', scheduleAnchor, { passive: true });
    } catch (err) {
        // MutationObserver can be unavailable in unusual embedded contexts.
    }
    window.setTimeout(labelOpenButton, 250);
    window.setTimeout(labelOpenButton, 1200);
    window.setTimeout(labelOpenButton, 2600);
})();
