(function () {
    'use strict';

    const UTILS = window.SimpAICanvasWorkbenchUtils || {};
    const nowIso = UTILS.nowIso || (() => new Date().toISOString());
    const clamp = UTILS.clamp || ((value, min, max) => Math.max(min, Math.min(max, value)));
    const sanitizeStoragePart = UTILS.sanitizeStoragePart || ((value) => String(value || 'guest').replace(/[^a-zA-Z0-9_.:-]/g, '_') || 'guest');
    const shortIdentity = UTILS.shortIdentity || ((value) => String(value || 'guest'));
    const t = UTILS.t || ((en, cn) => cn || en);
    const getUiLang = UTILS.getUiLang || (() => 'cn');

    const LEGACY_STORAGE_KEY = 'simpai.infiniteCanvasWorkbench.v1';
    const STORAGE_KEY_PREFIX = 'simpai.infiniteCanvasWorkbench.v1';
    const PROJECT_ID = 'default';
    const DEFAULT_SETTINGS = {
        __lang: getUiLang(),
        grid: true,
        snap: false,
        minimap: true,
        edgeLabels: true,
        reducedMotion: false,
        inspectorCollapsed: false
    };

    function getCanvasTitle() {
        return t('SimpAI Infinite Canvas', 'SimpAI 无限画布');
    }

    function getStorageScope() {
        const params = window.simpleaiTopbarSystemParams && typeof window.simpleaiTopbarSystemParams === 'object'
            ? window.simpleaiTopbarSystemParams
            : {};
        const accessMode = String(params.access_mode || '').toLowerCase();
        const role = String(params.user_role || '').toLowerCase();
        const userDid = String(params.user_did || '').trim();
        const isLocal = accessMode === 'local' || role === 'local';
        const mode = isLocal ? 'local' : 'multi';
        const owner = isLocal ? 'local' : sanitizeStoragePart(userDid || role || 'guest');
        const roleLabel = isLocal ? t('Local mode', 'Local 模式') : (role ? `${role} ${t('user', '用户')}` : t('Multi-user mode', '多用户模式'));
        const ownerLabel = isLocal ? t('Current browser', '当前浏览器') : shortIdentity(userDid || role || 'guest');
        return {
            mode,
            owner,
            label: `${roleLabel} / ${ownerLabel}`,
            location: t('User directory', '用户目录'),
            cacheLocation: t('Browser localStorage cache', '浏览器 localStorage 缓存'),
            allowLegacyFallback: isLocal
        };
    }

    function getStorageKey(scope) {
        const s = scope || getStorageScope();
        return `${STORAGE_KEY_PREFIX}:${sanitizeStoragePart(s.mode)}:${sanitizeStoragePart(s.owner)}`;
    }

    function defaultNodeSize(type) {
        const REGISTRY = window.SimpAICanvasWorkbenchRegistry || {};
        if (typeof REGISTRY.defaultNodeSize === 'function') return REGISTRY.defaultNodeSize(type);
        if (type === 'image') return { w: 264, h: 300 };
        if (type === 'note') return { w: 280, h: 180 };
        return { w: 220, h: 250 };
    }

    function createDefaultProject(options) {
        const opts = options || {};
        return {
            schema: 'simpai.canvas.workbench.v1',
            id: opts.projectId || PROJECT_ID,
            title: 'Untitled Canvas',
            created_at: nowIso(),
            updated_at: nowIso(),
            viewport: { x: 80, y: 80, zoom: 1 },
            settings: Object.assign({}, opts.defaultSettings || DEFAULT_SETTINGS),
            groups: [],
            nodes: [],
            edges: [],
            runs: [],
            batch_jobs: []
        };
    }

    function sanitizeProject(raw, options) {
        const opts = options || {};
        const settings = opts.defaultSettings || DEFAULT_SETTINGS;
        const nodeSize = typeof opts.defaultNodeSize === 'function' ? opts.defaultNodeSize : defaultNodeSize;
        const next = raw && typeof raw === 'object' ? raw : createDefaultProject(opts);
        next.schema = next.schema || 'simpai.canvas.workbench.v1';
        next.title = next.title || 'Untitled Canvas';
        next.created_at = next.created_at || nowIso();
        next.updated_at = next.updated_at || nowIso();
        next.viewport = Object.assign({ x: 80, y: 80, zoom: 1 }, next.viewport || {});
        next.viewport.zoom = clamp(Number(next.viewport.zoom) || 1, 0.15, 3);
        next.settings = Object.assign({}, settings, next.settings || {});
        if (!next.settings.__minimap_initialized) {
            next.settings.minimap = true;
            next.settings.__minimap_initialized = true;
        }
        next.groups = Array.isArray(next.groups) ? next.groups : [];
        next.groups.forEach((group, index) => {
            if (!group || typeof group !== 'object') return;
            group.id = group.id || `group_${index + 1}`;
            group.title = group.title || t('Group', '分组');
            group.x = Number.isFinite(Number(group.x)) ? Math.round(Number(group.x)) : 0;
            group.y = Number.isFinite(Number(group.y)) ? Math.round(Number(group.y)) : 0;
            group.w = Math.max(180, Math.round(Number(group.w || 360)));
            group.h = Math.max(120, Math.round(Number(group.h || 240)));
            group.color = String(group.color || '#14b8a6');
            group.alpha = clamp(Number(group.alpha ?? 0.16), 0.04, 0.72);
            group.shortcut = String(group.shortcut || '').trim().slice(0, 12);
            group.locked = !!group.locked;
        });
        next.nodes = Array.isArray(next.nodes) ? next.nodes : [];
        next.nodes.forEach((node) => {
            if (node && node.type === 'batch_images') node.type = 'batch_any';
            if (node && node.type === 'image') {
                if (!node.w || Number(node.w) <= 220) node.w = 264;
                if (!node.h || Number(node.h) <= 250) node.h = 300;
            }
            if (node && node.type === 'video') {
                if (!node.w || Number(node.w) <= 260) node.w = 340;
                if (!node.h || Number(node.h) <= 240) node.h = 320;
            }
            if (node && node.type === 'audio') {
                if (!node.w || Number(node.w) <= 260) node.w = 320;
                if (!node.h || Number(node.h) <= 180) node.h = 220;
            }
            if (node && node.type === 'compare') {
                const size = nodeSize('compare');
                if (!node.w || Number(node.w) < size.w) node.w = size.w;
                if (!node.h || Number(node.h) < size.h) node.h = size.h;
                node.inputs = Object.assign({ a: null, b: null }, node.inputs || {});
                node.params = Object.assign({ position: 50, mode: 'fit' }, node.params || {});
            }
            if (node && node.type === 'batch_any') {
                const size = nodeSize('batch_any');
                if (!node.w || Number(node.w) < size.w) node.w = size.w;
                if (!node.h || Number(node.h) < size.h) node.h = size.h;
                node.items = Array.isArray(node.items) ? node.items.filter(item => item && typeof item === 'object') : [];
                node.current_index = clamp(Number(node.current_index || 0), 0, Math.max(node.items.length - 1, 0));
                node.media_kind = node.media_kind || node.items[0]?.media_kind || '';
                node.params = Object.assign({ stop_on_error: true }, node.params || {});
                node.batch = Object.assign({ state: 'idle', run_ids: [], last_error: '' }, node.batch || {});
                const currentItem = node.items[node.current_index] || null;
                node.asset = currentItem?.asset || null;
                if ((currentItem?.media_kind || node.media_kind) === 'text') {
                    const textValue = typeof currentItem?.text === 'string'
                        ? currentItem.text
                        : (currentItem?.text && typeof currentItem.text === 'object' ? String(currentItem.text.value || '') : '');
                    node.text = Object.assign({}, node.text || {}, { value: textValue, updated_at: currentItem?.text?.updated_at || currentItem?.added_at || '' });
                }
            }
            if (node && node.type === 'tag_cart') {
                const size = nodeSize('tag_cart');
                if (!node.w || Number(node.w) < size.w) node.w = size.w;
                if (!node.h || Number(node.h) < size.h) node.h = size.h;
            }
            if (node && node.type === 'text_merge') {
                const size = nodeSize('text_merge');
                if (!node.w || Number(node.w) < size.w) node.w = size.w;
                if (!node.h || Number(node.h) < size.h) node.h = size.h;
                node.input_slots = Array.isArray(node.input_slots) && node.input_slots.length
                    ? Array.from(new Set(node.input_slots.map(slot => String(slot || '').trim()).filter(Boolean)))
                    : ['input_1', 'input_2'];
                node.text_inputs = node.text_inputs && typeof node.text_inputs === 'object' ? node.text_inputs : {};
                node.params = Object.assign({ separator: '' }, node.params || {});
            }
            if (node && node.type === 'note') {
                if (!node.w || Number(node.w) < 180) node.w = 260;
                if (!node.h || Number(node.h) < 120) node.h = 160;
                node.text = String(node.text ?? '');
                node.style = Object.assign({
                    color: '#f8fafc',
                    background: '#164e63',
                    font_size: 14
                }, node.style || {});
                node.style.font_size = clamp(Number(node.style.font_size || 14), 10, 42);
                if (node.tail && typeof node.tail === 'object') {
                    const target = node.tail.target && typeof node.tail.target === 'object' ? node.tail.target : {};
                    node.tail = {
                        enabled: !!node.tail.enabled,
                        target: {
                            x: Number.isFinite(Number(target.x)) ? Math.round(Number(target.x)) : Math.round(Number(node.x || 0) + Number(node.w || 260) + 130),
                            y: Number.isFinite(Number(target.y)) ? Math.round(Number(target.y)) : Math.round(Number(node.y || 0) + Number(node.h || 160) * 0.45)
                        }
                    };
                }
            }
        });
        next.edges = Array.isArray(next.edges) ? next.edges : [];
        next.runs = Array.isArray(next.runs) ? next.runs : [];
        next.batch_jobs = Array.isArray(next.batch_jobs) ? next.batch_jobs : [];
        next.batch_jobs.forEach((job, index) => {
            if (!job || typeof job !== 'object') return;
            job.id = job.id || `batch_${index + 1}`;
            job.script = job.script || 'X/Y/Z plot';
            job.axes = Array.isArray(job.axes) ? job.axes : [];
            job.variants = Array.isArray(job.variants) ? job.variants : [];
            job.run_ids = Array.isArray(job.run_ids) ? job.run_ids : [];
            job.status = job.status || 'planned';
        });
        return next;
    }

    function buildProjectStorageInfo(key, scope, migrated) {
        const s = scope || getStorageScope();
        return {
            kind: 'browser_local_storage_cache',
            key,
            scope: s.mode,
            owner: s.owner,
            label: s.label,
            location: s.cacheLocation || t('Browser localStorage cache', '浏览器 localStorage 缓存'),
            migrated_from_legacy: !!migrated
        };
    }

    function loadProject(key, scope, options) {
        try {
            const text = localStorage.getItem(key);
            if (text) {
                const loaded = sanitizeProject(JSON.parse(text), options);
                const storedStorage = loaded.storage && typeof loaded.storage === 'object' ? loaded.storage : {};
                loaded.storage = buildProjectStorageInfo(key, scope);
                if (storedStorage.asset_root) loaded.storage.asset_root = storedStorage.asset_root;
                return loaded;
            }
            if (scope && scope.allowLegacyFallback) {
                const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
                if (legacy) {
                    const loaded = sanitizeProject(JSON.parse(legacy), options);
                    const storedStorage = loaded.storage && typeof loaded.storage === 'object' ? loaded.storage : {};
                    loaded.storage = buildProjectStorageInfo(key, scope, true);
                    if (storedStorage.asset_root) loaded.storage.asset_root = storedStorage.asset_root;
                    return loaded;
                }
            }
            const next = createDefaultProject(options);
            next.storage = buildProjectStorageInfo(key, scope);
            return next;
        } catch (err) {
            console.warn('[SimpAI Canvas] failed to load project:', err);
        }
        const next = createDefaultProject(options);
        next.storage = buildProjectStorageInfo(key, scope);
        return next;
    }

    function cloneJson(value, fallback) {
        try {
            return JSON.parse(JSON.stringify(value ?? fallback));
        } catch (err) {
            return fallback;
        }
    }

    function compactProjectForStorage(source, options) {
        const opts = options || {};
        const maxInline = Number(opts.maxInlineDataUrlChars ?? 1800000);
        const cloneValue = typeof opts.cloneValue === 'function' ? opts.cloneValue : cloneJson;
        const next = cloneValue(source || createDefaultProject(opts), createDefaultProject(opts));
        const compactAsset = (asset) => {
            if (!asset || typeof asset !== 'object') return;
            const hasFileRef = !!(asset.path || asset.output_path || asset.preview_url || asset.original_output_path || asset.asset_relative_path || asset.relative_path);
            const dataUrlLength = String(asset.data_url || '').length;
            const shouldStrip = (opts.stripAllMaterializedDataUrls && hasFileRef) || dataUrlLength > maxInline;
            if (shouldStrip) delete asset.data_url;
            if ((opts.stripAllMaterializedDataUrls && hasFileRef) || String(asset.thumb || '').length > maxInline) delete asset.thumb;
        };
        if (next.storage && opts.stripStorage !== false) delete next.storage;
        (Array.isArray(next.nodes) ? next.nodes : []).forEach((node) => {
            compactAsset(node.asset);
            if (Array.isArray(node.assets)) node.assets.forEach(compactAsset);
            compactAsset(node.preview);
            if (node.last_response) delete node.last_response;
            if (node.chat && typeof node.chat === 'object') {
                if (Array.isArray(node.chat.pending_images)) node.chat.pending_images.forEach(compactAsset);
                if (Array.isArray(node.chat.messages)) {
                    node.chat.messages.forEach((message) => {
                        if (Array.isArray(message?.images)) message.images.forEach(compactAsset);
                    });
                }
            }
            const hasMaterializedAsset = !!(node.asset && (node.asset.path || node.asset.output_path || node.asset.preview_url || node.asset.original_output_path || node.asset.asset_relative_path || node.asset.relative_path))
                || (Array.isArray(node.assets) && node.assets.some(asset => asset && (asset.path || asset.output_path || asset.preview_url || asset.original_output_path || asset.asset_relative_path || asset.relative_path)));
            if (opts.stripAllMaterializedDataUrls && hasMaterializedAsset && node.preview) {
                delete node.preview.data_url;
                delete node.preview.thumb;
            }
            if (node.preview_frames) delete node.preview_frames;
            if (node.mask && (node.mask.path || node.mask.preview_url || String(node.mask.data_url || '').length > maxInline)) {
                delete node.mask.data_url;
            }
            if (node.source?.dry_run?.task_args_preview) delete node.source.dry_run.task_args_preview;
            if (Array.isArray(node.run_events) && node.run_events.length > 8) node.run_events = node.run_events.slice(-8);
            if (node.error_details?.traceback) delete node.error_details.traceback;
        });
        const runLimit = Math.max(0, Number(opts.runHistoryLimit ?? 12));
        const sourceRuns = Array.isArray(next.runs) ? next.runs : [];
        next.runs = (runLimit ? sourceRuns.slice(-runLimit) : []).map((run) => {
            const compactRun = {
                id: run?.id || '',
                state: run?.state || run?.status || '',
                preset_node_id: run?.preset_node_id || '',
                qwen_tts_node_id: run?.qwen_tts_node_id || '',
                producer_node_id: run?.producer_node_id || '',
                producer_type: run?.producer_type || '',
                mode: run?.mode || '',
                placeholder_node_id: run?.placeholder_node_id || '',
                task_id: run?.task_id || '',
                backend: run?.backend || '',
                message: run?.message || '',
                percent: run?.percent ?? null,
                resolved_seed: run?.resolved_seed ?? null,
                input_count: run?.input_count ?? null,
                output_count: run?.output_count ?? null,
                created_at: run?.created_at || '',
                finished_at: run?.finished_at || '',
                updated_at: run?.updated_at || '',
                error: run?.error || '',
                details: run?.details || ''
            };
            if (run?.asset) {
                compactRun.asset = cloneValue(run.asset, {});
                compactAsset(compactRun.asset);
            }
            if (Array.isArray(run?.assets) && run.assets.length) {
                compactRun.assets = run.assets.map(asset => cloneValue(asset, {}));
                compactRun.assets.forEach(compactAsset);
            }
            return compactRun;
        });
        return next;
    }

    window.SimpAICanvasWorkbenchProject = {
        LEGACY_STORAGE_KEY,
        STORAGE_KEY_PREFIX,
        PROJECT_ID,
        DEFAULT_SETTINGS,
        getCanvasTitle,
        getStorageScope,
        getStorageKey,
        createDefaultProject,
        sanitizeProject,
        loadProject,
        compactProjectForStorage,
        buildProjectStorageInfo
    };
})();
