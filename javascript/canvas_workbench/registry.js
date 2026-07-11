(function () {
    'use strict';

    const UTILS = window.SimpAICanvasWorkbenchUtils || {};
    const t = UTILS.t || ((en, cn) => cn || en);

    const SLOT_ORDER = [
        'scene_canvas_image',
        'scene_input_image1',
        'scene_input_image2',
        'scene_input_image3',
        'scene_input_image4',
        'scene_video',
        'scene_reference_video',
        'sam3_input_video',
        'sam3_mask_video',
        'scene_audio'
    ];
    const SLOT_LABELS = {
        scene_canvas_image: t('Canvas / Main Image', '画布 / 主图'),
        scene_input_image1: t('Input Image 1', '输入图 1'),
        scene_input_image2: t('Input Image 2', '输入图 2'),
        scene_input_image3: t('Input Image 3', '输入图 3'),
        scene_input_image4: t('Input Image 4', '输入图 4'),
        scene_video: t('Scene Video', '场景视频'),
        scene_reference_video: t('Reference Video', '参考视频'),
        sam3_input_video: t('SAM3 Input Video', 'SAM3 输入视频'),
        sam3_mask_video: t('SAM3 Mask Video', 'SAM3 遮罩视频'),
        scene_audio: t('Scene Audio', '场景音频')
    };
    const VLM_VERSION_CHOICES = [
        'Qwen3.5-9B-abliterated-Q4_K_M',
        'Qwen3.5-9B-abliterated-Q2_K',
        'Qwen3.5-9B-abliterated-Q6_K',
        'Qwen3.5-9B-abliterated-Q8_0',
        'Custom'
    ];
    const VLM_IMAGE_SLOTS = [
        { key: 'image_1', label: t('Image 1', '图像 1') },
        { key: 'image_2', label: t('Image 2', '图像 2') },
        { key: 'image_3', label: t('Image 3', '图像 3') }
    ];

    /* ──────────────────────────────────────────────
     * Classic Preset Node Constants
     * ────────────────────────────────────────────── */
    const CLASSIC_MODES = [
        { key: 't2i',      label: t('Text to Image', '文生图'), icon: '✏️',  tab: 'ip' },
        { key: 'ip',       label: t('Image Prompt', '图像提示'), icon: '🖼️', tab: 'ip' },
        { key: 'uov',      label: t('Upscale / Vary', '放大 / 变化'), icon: '🔍', tab: 'uov' },
        { key: 'inpaint',  label: t('Inpaint/Outpaint', '重绘 / 扩图'), icon: '🖌️', tab: 'inpaint' },
        { key: 'enhance',  label: t('Enhance', '细化'), icon: '✨', tab: 'enhance' }
    ];
    const CLASSIC_IP_MAX_IMAGES = 4;
    /* Full list matching modules.flags.ip_list = [cn_ip, cn_canny, cn_cpds, cn_ip_face, cn_pose] */
    const CLASSIC_IP_CONTROL_TYPES = [
        'ImagePrompt', 'PyraCanny', 'Depth', 'FaceSwap', 'OpenPose'
    ];
    /* Engine-specific IP type subsets matching main UI filtering in topbar.update_after_identity_sub */
    const CLASSIC_IP_FILTERS = {
        'default': ['ImagePrompt', 'PyraCanny', 'Depth', 'FaceSwap', 'OpenPose'],
        'wan_qwen_zimage': ['PyraCanny', 'Depth', 'OpenPose'],
        'il_v_pre': ['ImagePrompt', 'PyraCanny', 'Depth', 'OpenPose'],
    };
    const CLASSIC_UOV_METHODS_DEFAULT = [
        'Disabled',
        'Vary (Subtle)',
        'Vary (Strong)',
        'Upscale (1.5x)',
        'Upscale (2x)',
        'Upscale (Fast 2x)'
    ];
    const CLASSIC_UOV_METHODS_FLUX = [
        'Disabled',
        'Vary (Subtle)',
        'Vary (Strong)',
        'Vary (Hires.fix)',
        'Upscale (1.5x)',
        'Upscale (2x)',
        'Upscale (Fast 2x)'
    ];
    const CLASSIC_UOV_METHODS = CLASSIC_UOV_METHODS_DEFAULT;
    const CLASSIC_INPAINT_METHODS = [
        'Inpaint or Outpaint (default)',
        'Improve Detail (face, hand, eyes, etc.)',
        'Modify Content (add objects, change background, etc.)'
    ];
    const CLASSIC_ENHANCE_REGION_DEFAULTS = [
        { key: 'face', label: 'Face', prompt: 'face' },
        { key: 'hand', label: 'Hand', prompt: 'hand' },
        { key: 'eye', label: 'Eye', prompt: 'eye' }
    ];
    const CLASSIC_ENHANCE_UOV_PROCESSING_ORDER = [
        'Before First Enhancement',
        'After Last Enhancement'
    ];
    const CLASSIC_ENHANCE_UOV_PROMPT_TYPES = [
        'Original Prompts',
        'Last Filled Enhancement Prompts'
    ];
    const CLASSIC_ENHANCE_MASK_MODELS = ['u2net', 'u2netp', 'u2net_human_seg', 'u2net_cloth_seg', 'silueta', 'isnet-general-use', 'isnet-anime', 'sam'];
    const CLASSIC_ENHANCE_CLOTH_CATEGORIES = ['full', 'upper', 'lower'];
    const CLASSIC_ENHANCE_SAM_MODELS = ['vit_b', 'vit_l', 'vit_h'];
    const CLASSIC_OUTPAINT_DIRS = ['Left', 'Right', 'Top', 'Bottom'];
    const CLASSIC_INPAINT_ENGINES = {
        'SDXL': ['v2.6', 'v2.5', 'None'],
        'sd15_aio': ['powerpaint', 'None'],
        'flux_aio': ['fp8', 'None'],
        'il_v_pre_aio': ['NoobAI_Inpainting', 'None'],
        'nun_int4_aio': ['Nun_int4', 'None'],
        'nun_fp4_aio': ['Nun_fp4', 'None'],
        'wan_aio_cn': ['VACE'],
        'qwen_aio_cn': ['Qwen_Inpaint'],
        'z_image_turbo_aio_cn': ['LanPaint']
    };

    const DEFAULT_NODE_SIZES = {
        image: { w: 300, h: 360 },
        video: { w: 340, h: 320 },
        audio: { w: 320, h: 220 },
        preset: { w: 360, h: 420 },
        classic: { w: 380, h: 500 },
        config: { w: 320, h: 360 },
        result: { w: 340, h: 330 },
        compare: { w: 560, h: 520 },
        batch_any: { w: 360, h: 460 },
        xy_matrix: { w: 700, h: 520 },
        xyz_matrix: { w: 760, h: 560 },
        timeline: { w: 760, h: 520 },
        director_timeline: { w: 1180, h: 980 },
        media_browser: { w: 900, h: 640 },
        style_selector: { w: 390, h: 560 },
        text: { w: 300, h: 220 },
        text_merge: { w: 340, h: 360 },
        wildcards_helper: { w: 340, h: 430 },
        translation: { w: 320, h: 300 },
        note: { w: 280, h: 180 },
        tag_cart: { w: 1200, h: 800 },
        wd14: { w: 320, h: 360 },
        vlm: { w: 360, h: 520 },
        mask: { w: 320, h: 520 },
        sam3_video_mask: { w: 360, h: 560 },
        pose_studio: { w: 380, h: 520 },
        gaussian_studio: { w: 400, h: 560 },
        liveportrait_expression: { w: 420, h: 600 },
        qwen_tts_voice_design: { w: 360, h: 560 },
        qwen_tts_voice_clone: { w: 360, h: 580 },
        qwen_tts_custom_voice: { w: 360, h: 600 },
        qwen_tts_dialogue: { w: 380, h: 680 },
        fallback: { w: 220, h: 250 }
    };

    const nodeTypes = new Map();

    function registerNodeType(type, definition) {
        if (!type) return;
        nodeTypes.set(type, Object.assign({ type }, definition || {}));
    }

    function getNodeType(type) {
        return nodeTypes.get(type) || null;
    }

    [
        'image',
        'video',
        'audio',
        'result',
        'compare',
        'batch_any',
        'xy_matrix',
        'xyz_matrix',
        'timeline',
        'director_timeline',
        'media_browser',
        'style_selector',
        'preset',
        'classic',
        'text',
        'text_merge',
        'wildcards_helper',
        'translation',
        'tag_cart',
        'wd14',
        'vlm',
        'mask',
        'sam3_video_mask',
        'pose_studio',
        'gaussian_studio',
        'liveportrait_expression',
        'qwen_tts_voice_design',
        'qwen_tts_voice_clone',
        'qwen_tts_custom_voice',
        'qwen_tts_dialogue',
        'models_config',
        'styles_config',
        'resolution_config',
        'advanced_config',
        'output'
    ].forEach((type) => registerNodeType(type, { builtIn: true }));

    window.SimpAICanvasWorkbenchRegistry = {
        SLOT_ORDER,
        SLOT_LABELS,
        VLM_VERSION_CHOICES,
        VLM_IMAGE_SLOTS,
        DEFAULT_NODE_SIZES,
        /* Classic constants */
        CLASSIC_MODES,
        CLASSIC_IP_MAX_IMAGES,
        CLASSIC_IP_CONTROL_TYPES,
        CLASSIC_IP_FILTERS,
        CLASSIC_UOV_METHODS,
        CLASSIC_UOV_METHODS_DEFAULT,
        CLASSIC_UOV_METHODS_FLUX,
        CLASSIC_INPAINT_METHODS,
        CLASSIC_OUTPAINT_DIRS,
        CLASSIC_INPAINT_ENGINES,
        CLASSIC_ENHANCE_REGION_DEFAULTS,
        CLASSIC_ENHANCE_UOV_PROCESSING_ORDER,
        CLASSIC_ENHANCE_UOV_PROMPT_TYPES,
        CLASSIC_ENHANCE_MASK_MODELS,
        CLASSIC_ENHANCE_CLOTH_CATEGORIES,
        CLASSIC_ENHANCE_SAM_MODELS,
        /* API */
        defaultNodeSize: (type) => DEFAULT_NODE_SIZES[type] || DEFAULT_NODE_SIZES.fallback,
        registerNodeType,
        getNodeType,
        listNodeTypes: () => Array.from(nodeTypes.values())
    };
})();
