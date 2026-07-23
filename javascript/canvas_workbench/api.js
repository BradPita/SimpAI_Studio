(function () {
    'use strict';

    async function postJson(endpoint, payload, options) {
        const opts = options || {};
        const emptyError = opts.emptyError || 'empty response';
        const requestError = opts.requestError || 'request failed';
        try {
            const bodyPayload = Object.assign({}, payload || {});
            delete bodyPayload.signal;
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(bodyPayload),
                signal: opts.signal
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
                    details: data?.details || response.statusText || '',
                    errors: data?.errors || []
                });
            }
            return data || { ok: false, error: emptyError };
        } catch (err) {
            if (err?.name === 'AbortError') {
                return { ok: false, aborted: true, error: 'aborted' };
            }
            const message = err?.message || String(err || requestError);
            try {
                window.dispatchEvent(new CustomEvent('simpai:backend-request-failed', {
                    detail: { endpoint, error: message, at: new Date().toISOString() }
                }));
            } catch (eventErr) {}
            return { ok: false, error: message };
        }
    }

    function dryRun(payload) {
        return postJson('/canvas-workbench/dry-run', payload, {
            emptyError: 'empty dry-run response',
            requestError: 'dry-run request failed'
        });
    }

    function saveProject(payload) {
        return postJson('/canvas-workbench/project-save', payload, {
            emptyError: 'empty project-save response',
            requestError: 'project-save request failed'
        });
    }

    function loadProject(payload) {
        return postJson('/canvas-workbench/project-load', payload, {
            emptyError: 'empty project-load response',
            requestError: 'project-load request failed'
        });
    }

    function listProjects(payload) {
        return postJson('/canvas-workbench/project-list', payload, {
            emptyError: 'empty project-list response',
            requestError: 'project-list request failed'
        });
    }

    function deleteProject(payload) {
        return postJson('/canvas-workbench/project-delete', payload, {
            emptyError: 'empty project-delete response',
            requestError: 'project-delete request failed'
        });
    }

    function clearProject(payload) {
        return postJson('/canvas-workbench/project-clear', payload, {
            emptyError: 'empty project-clear response',
            requestError: 'project-clear request failed'
        });
    }

    function saveTemplate(payload) {
        return postJson('/canvas-workbench/template-save', payload, {
            emptyError: 'empty template-save response',
            requestError: 'template-save request failed'
        });
    }

    function listTemplates(payload) {
        return postJson('/canvas-workbench/template-list', payload || {}, {
            emptyError: 'empty template-list response',
            requestError: 'template-list request failed'
        });
    }

    function loadTemplate(payload) {
        return postJson('/canvas-workbench/template-load', payload, {
            emptyError: 'empty template-load response',
            requestError: 'template-load request failed'
        });
    }

    function deleteTemplate(payload) {
        return postJson('/canvas-workbench/template-delete', payload, {
            emptyError: 'empty template-delete response',
            requestError: 'template-delete request failed'
        });
    }

    function runNode(payload) {
        return postJson('/canvas-workbench/run-node', payload, {
            emptyError: 'empty run-node response',
            requestError: 'run-node request failed'
        });
    }

    function pollRun(runId, options) {
        const payload = { run_id: runId };
        if (options && options.after_preview_serial !== undefined) {
            payload.after_preview_serial = options.after_preview_serial;
        }
        return postJson('/canvas-workbench/poll-run', payload, {
            emptyError: 'empty poll response',
            requestError: 'poll request failed'
        }).then((data) => {
            if (data && data.run_id === undefined) data.run_id = runId;
            return data;
        });
    }

    function controlRun(runId, action) {
        return postJson('/canvas-workbench/control-run', { run_id: runId, action }, {
            emptyError: 'empty control response',
            requestError: 'control request failed'
        }).then((data) => {
            if (data && data.run_id === undefined) data.run_id = runId;
            return data;
        });
    }

    function xyzAxisOptions(payload) {
        return postJson('/canvas-workbench/xyz/axis-options', payload || {}, {
            emptyError: 'empty X/Y/Z axis options response',
            requestError: 'X/Y/Z axis options request failed'
        });
    }

    function xyzPreview(payload) {
        return postJson('/canvas-workbench/xyz/preview', payload, {
            emptyError: 'empty X/Y/Z preview response',
            requestError: 'X/Y/Z preview request failed'
        });
    }

    function xyzRun(payload) {
        return postJson('/canvas-workbench/xyz/run', payload, {
            emptyError: 'empty X/Y/Z run response',
            requestError: 'X/Y/Z run request failed'
        });
    }

    function xyzPoll(jobId) {
        return postJson('/canvas-workbench/xyz/poll', { job_id: jobId }, {
            emptyError: 'empty X/Y/Z poll response',
            requestError: 'X/Y/Z poll request failed'
        }).then((data) => {
            if (data && data.job_id === undefined) data.job_id = jobId;
            return data;
        });
    }

    function xyzControl(jobId, action) {
        return postJson('/canvas-workbench/xyz/control', { job_id: jobId, action }, {
            emptyError: 'empty X/Y/Z control response',
            requestError: 'X/Y/Z control request failed'
        }).then((data) => {
            if (data && data.job_id === undefined) data.job_id = jobId;
            return data;
        });
    }

    function xyzRenderGrid(payload) {
        return postJson('/canvas-workbench/xyz/render-grid', payload, {
            emptyError: 'empty X/Y/Z render-grid response',
            requestError: 'X/Y/Z render-grid request failed'
        });
    }

    function qwenTtsRun(payload) {
        return postJson('/canvas-workbench/qwen-tts-run', payload, {
            emptyError: 'empty Qwen TTS response',
            requestError: 'Qwen TTS request failed'
        });
    }

    function qwenTtsPoll(jobId) {
        return postJson('/canvas-workbench/qwen-tts-poll', { job_id: jobId }, {
            emptyError: 'empty Qwen TTS poll response',
            requestError: 'Qwen TTS poll failed'
        }).then((data) => {
            if (data && data.job_id === undefined) data.job_id = jobId;
            return data;
        });
    }

    function qwenTtsControl(jobId, action) {
        return postJson('/canvas-workbench/qwen-tts-control', { job_id: jobId, action }, {
            emptyError: 'empty Qwen TTS control response',
            requestError: 'Qwen TTS control failed'
        }).then((data) => {
            if (data && data.job_id === undefined) data.job_id = jobId;
            return data;
        });
    }

    function qwenTtsPresets(payload) {
        return postJson('/canvas-workbench/qwen-tts-presets', payload || {}, {
            emptyError: 'empty Qwen TTS presets response',
            requestError: 'Qwen TTS presets request failed'
        });
    }

    function modelCatalog(payload) {
        return postJson('/canvas-workbench/model-catalog', payload, {
            emptyError: 'empty model catalog response',
            requestError: 'model catalog request failed'
        });
    }

    function presetCatalog(payload) {
        return postJson('/canvas-workbench/preset-catalog', payload || {}, {
            emptyError: 'empty preset catalog response',
            requestError: 'preset catalog request failed'
        });
    }

    function modelBrowserQuery(payload) {
        return postJson('/model-browser/query', payload || {}, {
            emptyError: 'empty model-browser response',
            requestError: 'model-browser query failed'
        });
    }

    function modelBrowserFetchMetadata(payload) {
        return postJson('/model-browser/fetch-metadata', payload || {}, {
            emptyError: 'empty model-browser metadata response',
            requestError: 'model-browser metadata fetch failed'
        });
    }

    function modelBrowserFetchBatch(payload) {
        return postJson('/model-browser/fetch-batch', payload || {}, {
            emptyError: 'empty model-browser batch response',
            requestError: 'model-browser batch fetch failed'
        });
    }

    function presetModelStatus(payload) {
        return postJson('/canvas-workbench/preset-model-status', payload, {
            emptyError: 'empty preset model status response',
            requestError: 'preset model status request failed'
        });
    }

    function presetModelDownloads(payload) {
        return postJson('/canvas-workbench/preset-model-downloads', payload, {
            emptyError: 'empty preset model download response',
            requestError: 'preset model download request failed'
        });
    }

    function listAssets(payload) {
        return postJson('/canvas-workbench/list-assets', payload, {
            emptyError: 'empty asset list response',
            requestError: 'asset list request failed'
        });
    }

    function mediaGallery(payload) {
        return postJson('/canvas-workbench/media-gallery', payload || {}, {
            emptyError: 'empty media gallery response',
            requestError: 'media gallery request failed'
        });
    }

    function mediaGalleryDelete(payload) {
        return postJson('/canvas-workbench/media-gallery/delete', payload || {}, {
            emptyError: 'empty media gallery delete response',
            requestError: 'media gallery delete failed'
        });
    }

    function deleteAssets(payload) {
        return postJson('/canvas-workbench/delete-assets', payload, {
            emptyError: 'empty asset delete response',
            requestError: 'asset delete request failed'
        });
    }

    function materializeAsset(payload) {
        return postJson('/canvas-workbench/materialize-asset', payload, {
            emptyError: 'empty asset materialize response',
            requestError: 'asset materialize request failed'
        });
    }

    function generateMask(payload) {
        return postJson('/canvas-workbench/generate-mask', payload, {
            emptyError: 'empty mask generation response',
            requestError: 'mask generation request failed'
        });
    }

    function generateCameraMotionReference(payload) {
        return postJson('/canvas-workbench/generate-camera-motion-reference', payload, {
            emptyError: 'empty camera motion reference response',
            requestError: 'camera motion reference request failed'
        });
    }

    function generateSam3VideoMask(payload) {
        return postJson('/canvas-workbench/generate-sam3-video-mask', payload, {
            emptyError: 'empty SAM3 video mask response',
            requestError: 'SAM3 video mask request failed',
            signal: payload?.signal
        });
    }

    function cancelSam3VideoMask(payload) {
        return postJson('/canvas-workbench/cancel-sam3-video-mask', payload, {
            emptyError: 'empty SAM3 cancel response',
            requestError: 'SAM3 cancel request failed'
        });
    }

    function normalizeSam3MaskVideo(payload) {
        return postJson('/canvas-workbench/normalize-sam3-mask-video', payload, {
            emptyError: 'empty SAM3 mask upload response',
            requestError: 'SAM3 mask upload request failed'
        });
    }

    function poseStudioStatus(payload) {
        return postJson('/pose-studio/status', payload || {}, {
            emptyError: 'empty Pose Studio status response',
            requestError: 'Pose Studio status request failed'
        });
    }

    function poseStudioCharacterPreview(payload) {
        return postJson('/pose-studio/character/update-preview', payload || {}, {
            emptyError: 'empty Pose Studio character response',
            requestError: 'Pose Studio character request failed'
        });
    }

    function poseStudioLibraryList(payload) {
        return postJson('/pose-studio/library/list', payload || {}, {
            emptyError: 'empty Pose Studio library response',
            requestError: 'Pose Studio library request failed'
        });
    }

    function poseStudioLibraryGet(payload) {
        return postJson('/pose-studio/library/get', payload || {}, {
            emptyError: 'empty Pose Studio pose response',
            requestError: 'Pose Studio pose request failed'
        });
    }

    function poseStudioLibrarySave(payload) {
        return postJson('/pose-studio/library/save', payload || {}, {
            emptyError: 'empty Pose Studio save response',
            requestError: 'Pose Studio save request failed'
        });
    }

    function poseStudioLibraryDelete(payload) {
        return postJson('/pose-studio/library/delete', payload || {}, {
            emptyError: 'empty Pose Studio delete response',
            requestError: 'Pose Studio delete request failed'
        });
    }

    function poseStudioLibraryRename(payload) {
        return postJson('/pose-studio/library/rename', payload || {}, {
            emptyError: 'empty Pose Studio rename response',
            requestError: 'Pose Studio rename request failed'
        });
    }

    function poseStudioImportStatus(payload) {
        return postJson('/pose-studio/import/status', payload || {}, {
            emptyError: 'empty Pose Studio import status response',
            requestError: 'Pose Studio import status request failed'
        });
    }

    function poseStudioImportReference(payload) {
        return postJson('/pose-studio/import/reference-image', payload || {}, {
            emptyError: 'empty Pose Studio reference import response',
            requestError: 'Pose Studio reference import request failed'
        });
    }

    function poseStudioRenderOverlay(payload) {
        return postJson('/pose-studio/render-overlay', payload || {}, {
            emptyError: 'empty Pose Studio overlay response',
            requestError: 'Pose Studio overlay request failed'
        });
    }

    function poseStudioExport(payload) {
        return postJson('/pose-studio/canvas/export', payload || {}, {
            emptyError: 'empty Pose Studio export response',
            requestError: 'Pose Studio export request failed'
        });
    }

    function gaussianStudioStatus(payload) {
        return postJson('/gaussian-studio/status', payload || {}, {
            emptyError: 'empty Gaussian Studio status response',
            requestError: 'Gaussian Studio status request failed'
        });
    }

    function gaussianStudioPredict(payload) {
        return postJson('/gaussian-studio/predict', payload || {}, {
            emptyError: 'empty Gaussian Studio predict response',
            requestError: 'Gaussian Studio predict request failed'
        });
    }

    function gaussianStudioExport(payload) {
        return postJson('/gaussian-studio/canvas/export', payload || {}, {
            emptyError: 'empty Gaussian Studio export response',
            requestError: 'Gaussian Studio export request failed'
        });
    }

    function renderTimeline(payload) {
        return postJson('/canvas-workbench/render-timeline', payload, {
            emptyError: 'empty timeline render response',
            requestError: 'timeline render request failed'
        });
    }

    function renderTimelineFrame(payload) {
        return postJson('/canvas-workbench/render-timeline-frame', payload, {
            emptyError: 'empty timeline frame response',
            requestError: 'timeline frame request failed'
        });
    }

    function wd14Tag(payload) {
        return postJson('/canvas-workbench/wd14-tag', payload, {
            emptyError: 'empty WD14 response',
            requestError: 'WD14 request failed'
        });
    }

    function vlmRun(payload, options) {
        const opts = options || {};
        return postJson('/canvas-workbench/vlm-run', payload, {
            emptyError: 'empty VLM response',
            requestError: 'VLM request failed',
            signal: opts.signal
        });
    }

    function vlmCancel(payload) {
        return postJson('/canvas-workbench/vlm-cancel', payload, {
            emptyError: 'empty VLM cancel response',
            requestError: 'VLM cancel failed'
        });
    }

    function vlmModelStatus(payload) {
        return postJson('/canvas-workbench/vlm-model-status', payload, {
            emptyError: 'empty VLM model status response',
            requestError: 'VLM model status failed'
        });
    }

    function vlmModelDownloads(payload) {
        return postJson('/canvas-workbench/vlm-model-downloads', payload, {
            emptyError: 'empty VLM model download response',
            requestError: 'VLM model download failed'
        });
    }

    function customLlmModels(payload) {
        return postJson('/canvas-workbench/custom-llm-models', payload, {
            emptyError: 'empty custom LLM model response',
            requestError: 'custom LLM model request failed'
        });
    }

    function vlmSkills(payload) {
        return postJson('/canvas-workbench/vlm-skills', payload || {}, {
            emptyError: 'empty VLM skills response',
            requestError: 'VLM skills request failed'
        });
    }

    function vlmSystemPromptTemplates(payload) {
        return postJson('/vlm-system-prompt-templates', payload || {}, {
            emptyError: 'empty VLM system prompt template response',
            requestError: 'VLM system prompt template request failed'
        });
    }

    function danbooruTagLookup(payload) {
        return postJson('/canvas-agent/danbooru-tags/lookup', payload || {}, {
            emptyError: 'empty Danbooru tag lookup response',
            requestError: 'Danbooru tag lookup failed'
        });
    }

    function danbooruAutocomplete(payload) {
        return postJson('/canvas-workbench/danbooru-autocomplete', payload || {}, {
            emptyError: 'empty Danbooru autocomplete response',
            requestError: 'Danbooru autocomplete failed'
        });
    }

    function danbooruGalleryImportPreview(payload) {
        return postJson('/canvas-agent/danbooru-gallery/import-preview', payload || {}, {
            emptyError: 'empty Danbooru Gallery import preview response',
            requestError: 'Danbooru Gallery import preview failed'
        });
    }

    function characterGlossary(payload) {
        return postJson('/canvas-agent/character-glossary', payload || {}, {
            emptyError: 'empty character glossary response',
            requestError: 'character glossary request failed'
        });
    }

    function promptPreflight(payload) {
        return postJson('/canvas-agent/prompt-preflight', payload || {}, {
            emptyError: 'empty prompt preflight response',
            requestError: 'prompt preflight failed'
        });
    }

    function promptPreflightAcceptance(payload) {
        return postJson('/canvas-agent/prompt-preflight/acceptance', payload || {}, {
            emptyError: 'empty prompt preflight acceptance response',
            requestError: 'prompt preflight acceptance failed'
        });
    }

    function wildcardsCatalog(payload) {
        return postJson('/canvas-workbench/wildcards/catalog', payload || {}, {
            emptyError: 'empty wildcards catalog response',
            requestError: 'wildcards catalog failed'
        });
    }

    function wildcardsHelperTag(payload) {
        return postJson('/canvas-workbench/wildcards/helper-tag', payload || {}, {
            emptyError: 'empty wildcards helper response',
            requestError: 'wildcards helper failed'
        });
    }

    function wildcardsPreview(payload) {
        return postJson('/canvas-workbench/wildcards/preview', payload || {}, {
            emptyError: 'empty wildcards preview response',
            requestError: 'wildcards preview failed'
        });
    }

    function personalWildcards(payload) {
        return postJson('/canvas-workbench/wildcards/personal', payload || {}, {
            emptyError: 'empty personal wildcards response',
            requestError: 'personal wildcards request failed'
        });
    }

    function vlmUnload(payload) {
        return postJson('/canvas-workbench/vlm-unload', payload, {
            emptyError: 'empty VLM unload response',
            requestError: 'VLM unload failed'
        });
    }

    function translateRun(payload) {
        return postJson('/canvas-workbench/translate-run', payload, {
            emptyError: 'empty translate response',
            requestError: 'translate request failed'
        });
    }

    function translatePoll(jobId) {
        return postJson('/canvas-workbench/translate-poll', { job_id: jobId }, {
            emptyError: 'empty translate poll response',
            requestError: 'translate poll request failed'
        }).then((data) => {
            if (data && data.job_id === undefined) data.job_id = jobId;
            return data;
        });
    }

    window.SimpAICanvasWorkbenchApi = {
        postJson,
        saveProject,
        loadProject,
        listProjects,
        deleteProject,
        clearProject,
        saveTemplate,
        listTemplates,
        loadTemplate,
        deleteTemplate,
        dryRun,
        runNode,
        pollRun,
        controlRun,
        xyzAxisOptions,
        xyzPreview,
        xyzRun,
        xyzPoll,
        xyzControl,
        xyzRenderGrid,
        qwenTtsRun,
        qwenTtsPoll,
        qwenTtsControl,
        qwenTtsPresets,
        modelCatalog,
        presetCatalog,
        modelBrowserQuery,
        modelBrowserFetchMetadata,
        modelBrowserFetchBatch,
        presetModelStatus,
        presetModelDownloads,
        listAssets,
        mediaGallery,
        mediaGalleryDelete,
        deleteAssets,
        materializeAsset,
        generateMask,
        generateCameraMotionReference,
        generateSam3VideoMask,
        cancelSam3VideoMask,
        normalizeSam3MaskVideo,
        poseStudioStatus,
        poseStudioCharacterPreview,
        poseStudioLibraryList,
        poseStudioLibraryGet,
        poseStudioLibrarySave,
        poseStudioLibraryDelete,
        poseStudioLibraryRename,
        poseStudioImportStatus,
        poseStudioImportReference,
        poseStudioRenderOverlay,
        poseStudioExport,
        gaussianStudioStatus,
        gaussianStudioPredict,
        gaussianStudioExport,
        renderTimeline,
        renderTimelineFrame,
        wd14Tag,
        vlmRun,
        vlmCancel,
        vlmModelStatus,
        vlmModelDownloads,
        customLlmModels,
        vlmSkills,
        vlmSystemPromptTemplates,
        danbooruTagLookup,
        danbooruAutocomplete,
        danbooruGalleryImportPreview,
        characterGlossary,
        promptPreflight,
        promptPreflightAcceptance,
        wildcardsCatalog,
        wildcardsHelperTag,
        wildcardsPreview,
        personalWildcards,
        vlmUnload,
        translateRun,
        translatePoll
    };
})();
