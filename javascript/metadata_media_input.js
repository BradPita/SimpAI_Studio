(function () {
    'use strict';

    const ROOT_ID = 'metadata_input_image';
    const FILE_INPUT_SELECTOR = `#${ROOT_ID} input[type="file"]`;
    const PREVIEW_CLASS = 'simpai-metadata-local-preview';
    const HAS_MEDIA_CLASS = 'simpai-metadata-has-media';
    const DRAG_OVER_CLASS = 'simpai-metadata-drag-over';
    const MEDIA_EXTENSION_PATTERN = /\.(?:avif|bmp|gif|heic|heif|jpe?g|m4v|mkv|mov|mp4|mpeg|mpg|png|webm|webp)$/i;

    let currentFile = null;
    let currentObjectUrl = '';
    let observedRoot = null;
    let rootObserver = null;
    let renderFrame = 0;
    let replacementInProgress = false;

    function getRoot() {
        return document.getElementById(ROOT_ID);
    }

    function isMediaFile(file) {
        if (!(file instanceof File)) return false;
        const mime = String(file.type || '').toLowerCase();
        if (mime.startsWith('image/') || mime.startsWith('video/')) return true;
        return !mime && MEDIA_EXTENSION_PATTERN.test(String(file.name || ''));
    }

    function isVideoFile(file) {
        const mime = String(file?.type || '').toLowerCase();
        if (mime.startsWith('video/')) return true;
        return !mime && /\.(?:m4v|mkv|mov|mp4|mpeg|mpg|webm)$/i.test(String(file?.name || ''));
    }

    function dataTransferMayContainMedia(dataTransfer) {
        if (!dataTransfer) return false;
        const files = Array.from(dataTransfer.files || []);
        if (files.some(isMediaFile)) return true;
        return Array.from(dataTransfer.items || []).some((item) => {
            if (item.kind !== 'file') return false;
            const mime = String(item.type || '').toLowerCase();
            return !mime || mime.startsWith('image/') || mime.startsWith('video/');
        });
    }

    function eventHitsRoot(event) {
        const root = getRoot();
        if (!root) return false;
        const path = typeof event.composedPath === 'function' ? event.composedPath() : [];
        if (path.some((node) => node === root || node?.id === ROOT_ID)) return true;
        if (event.target?.closest?.(`#${ROOT_ID}`)) return true;
        const hovered = document.elementFromPoint(event.clientX, event.clientY);
        return !!hovered?.closest?.(`#${ROOT_ID}`);
    }

    function previewKey(file) {
        return [file.name || '', file.size || 0, file.type || '', file.lastModified || 0].join('|');
    }

    function removeRenderedPreview(root = getRoot()) {
        root?.querySelectorAll?.(`.${PREVIEW_CLASS}`).forEach((node) => node.remove());
        root?.classList.remove(HAS_MEDIA_CLASS);
    }

    function revokeObjectUrl() {
        if (!currentObjectUrl) return;
        URL.revokeObjectURL(currentObjectUrl);
        currentObjectUrl = '';
    }

    function clearCurrentPreview() {
        currentFile = null;
        revokeObjectUrl();
        removeRenderedPreview();
    }

    function renderCurrentPreview() {
        renderFrame = 0;
        const root = getRoot();
        if (!root || !currentFile || !currentObjectUrl) return;
        const key = previewKey(currentFile);
        const existing = root.querySelector(`.${PREVIEW_CLASS}`);
        if (existing?.dataset.previewKey === key) {
            root.classList.add(HAS_MEDIA_CLASS);
            return;
        }
        removeRenderedPreview(root);
        const preview = document.createElement('div');
        preview.className = PREVIEW_CLASS;
        preview.dataset.previewKey = key;
        if (isVideoFile(currentFile)) {
            const video = document.createElement('video');
            video.src = currentObjectUrl;
            video.controls = true;
            video.preload = 'metadata';
            video.playsInline = true;
            preview.appendChild(video);
        } else {
            const image = document.createElement('img');
            image.src = currentObjectUrl;
            image.alt = '';
            image.draggable = false;
            preview.appendChild(image);
        }
        root.appendChild(preview);
        root.classList.add(HAS_MEDIA_CLASS);
    }

    function scheduleRender() {
        if (renderFrame) return;
        renderFrame = window.requestAnimationFrame(renderCurrentPreview);
    }

    function setCurrentFile(file) {
        if (!isMediaFile(file)) return false;
        if (currentFile !== file) {
            revokeObjectUrl();
            currentFile = file;
            currentObjectUrl = URL.createObjectURL(file);
        }
        scheduleRender();
        return true;
    }

    function waitForFileInput(root, timeoutMs = 2000) {
        const currentInput = root?.querySelector('input[type="file"]');
        if (currentInput) return Promise.resolve(currentInput);
        if (!root) return Promise.resolve(null);

        return new Promise((resolve) => {
            let timer = 0;
            const observer = new MutationObserver(() => {
                const input = root.querySelector('input[type="file"]');
                if (!input) return;
                observer.disconnect();
                if (timer) window.clearTimeout(timer);
                resolve(input);
            });
            observer.observe(root, { childList: true, subtree: true });
            timer = window.setTimeout(() => {
                observer.disconnect();
                resolve(null);
            }, timeoutMs);
        });
    }

    async function replaceMetadataFile(file) {
        if (!setCurrentFile(file)) return false;
        const root = getRoot();
        if (!root) return false;
        let input = root.querySelector('input[type="file"]');
        try {
            if (!input) {
                const clearButton = root.querySelector('.icon-button-wrapper button:last-of-type');
                if (!clearButton) return false;
                replacementInProgress = true;
                clearButton.click();
                input = await waitForFileInput(root);
            }
            if (!input) {
                clearCurrentPreview();
                return false;
            }
            const transfer = new DataTransfer();
            transfer.items.add(file);
            input.files = transfer.files;
            input.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
            return true;
        } catch (error) {
            console.warn('[SimpAI] Failed to replace metadata media input.', error);
            return false;
        } finally {
            replacementInProgress = false;
        }
    }

    function clearDragState() {
        getRoot()?.classList.remove(DRAG_OVER_CLASS);
    }

    function handleFileInputChange(event) {
        const file = Array.from(event.currentTarget?.files || event.target?.files || []).find(isMediaFile);
        if (file) setCurrentFile(file);
    }

    function bindCurrentFileInput() {
        const input = getRoot()?.querySelector('input[type="file"]');
        if (!input || input.dataset.simpaiMetadataPreviewBound === '1') return;
        input.dataset.simpaiMetadataPreviewBound = '1';
        input.addEventListener('change', handleFileInputChange);
    }

    function watchCurrentRoot() {
        const root = getRoot();
        if (root === observedRoot) return;
        rootObserver?.disconnect();
        observedRoot = root;
        if (!root) return;
        rootObserver = new MutationObserver(() => {
            bindCurrentFileInput();
            scheduleRender();
        });
        rootObserver.observe(root, { childList: true, subtree: true });
        bindCurrentFileInput();
        scheduleRender();
    }

    document.addEventListener('change', (event) => {
        const input = event.target?.matches?.(FILE_INPUT_SELECTOR) ? event.target : null;
        if (input) handleFileInputChange(event);
    }, true);

    document.addEventListener('click', (event) => {
        if (!eventHitsRoot(event)) return;
        if (replacementInProgress) return;
        const path = typeof event.composedPath === 'function' ? event.composedPath() : [];
        const button = path.find((node) => node?.tagName === 'BUTTON' && node?.closest?.(`#${ROOT_ID}`));
        if (!button || button.closest('.file-preview-holder')) return;
        window.setTimeout(() => {
            const root = getRoot();
            const input = root?.querySelector('input[type="file"]');
            if (!input?.files?.length && !root?.querySelector('.file-preview-holder')) clearCurrentPreview();
        }, 80);
    }, true);

    document.addEventListener('dragenter', (event) => {
        if (!eventHitsRoot(event) || !dataTransferMayContainMedia(event.dataTransfer)) return;
        event.preventDefault();
        getRoot()?.classList.add(DRAG_OVER_CLASS);
    }, true);

    document.addEventListener('dragover', (event) => {
        if (!eventHitsRoot(event) || !dataTransferMayContainMedia(event.dataTransfer)) return;
        event.preventDefault();
        event.stopPropagation();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        getRoot()?.classList.add(DRAG_OVER_CLASS);
    }, true);

    document.addEventListener('dragleave', (event) => {
        const hovered = document.elementFromPoint(event.clientX, event.clientY);
        if (!hovered?.closest?.(`#${ROOT_ID}`)) clearDragState();
    }, true);

    document.addEventListener('drop', (event) => {
        if (!eventHitsRoot(event)) return;
        const files = Array.from(event.dataTransfer?.files || []);
        if (!files.length) return;
        event.preventDefault();
        event.stopPropagation();
        clearDragState();
        const mediaFile = files.find(isMediaFile);
        if (mediaFile) void replaceMetadataFile(mediaFile);
    }, true);

    document.addEventListener('dragend', clearDragState, true);
    window.addEventListener('blur', clearDragState);
    window.addEventListener('beforeunload', revokeObjectUrl);

    const start = () => {
        watchCurrentRoot();
        const pageObserver = new MutationObserver(watchCurrentRoot);
        pageObserver.observe(document.body, { childList: true, subtree: true });
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
