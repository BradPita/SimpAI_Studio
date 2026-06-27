import csv
import json
import os
import random
import re

import modules.canvas_danbooru_service as canvas_danbooru_service


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECOMMENDATIONS_DIR = os.path.join(ROOT_DIR, "presets", "scene_prompt_recommendations")
RANDOM_PROMPT_ASSOCIATIONS_FILE = os.path.join(RECOMMENDATIONS_DIR, "random_prompt_associations.csv")
RANDOM_PROMPT_NOISE_FILE = os.path.join(RECOMMENDATIONS_DIR, "random_prompt_noise.csv")
RANDOM_PROMPT_CHARACTERS_FILE = os.path.join(RECOMMENDATIONS_DIR, "random_prompt_characters.csv")
RANDOM_PROMPT_ADULT_SLOTS_FILE = os.path.join(ROOT_DIR, "docs", "adult_trigger_slots.csv")
RANDOM_PROMPT_ADULT_NEGATIVE_FILE = os.path.join(ROOT_DIR, "docs", "adult_negative_conflicts.csv")
RANDOM_PROMPT_NSFW_ENV = "SIMPAI_DEV_RANDOM_PROMPT_NSFW"

_random_prompt_association_cache = None
_random_prompt_noise_cache = None
_random_prompt_character_cache = None
_random_prompt_adult_slot_cache = None
_random_prompt_adult_negative_cache = None
RANDOM_CHARACTER_SAMPLE_POOL = 600

PROMPT_TARGETS = {
    "positive_prompt": "positive_prompt",
    "prompt": "positive_prompt",
    "main": "positive_prompt",
    "scene_additional_prompt": "scene_additional_prompt",
    "additional_prompt": "scene_additional_prompt",
    "scene_additional_prompt_2": "scene_additional_prompt_2",
    "additional_prompt_2": "scene_additional_prompt_2",
}

PROMPT_MODES = {"replace", "append"}

SHARED_RECOMMENDATION_FILES = {
    "text_to_video": "_text_to_video.csv",
    "image_to_video": "_image_to_video.csv",
    "image_edit": "_image_edit.csv",
}

IMAGE_EDIT_SHARED_PRESETS = {
    "Bernini-ImageEdit",
    "Flux2-KleinEdit",
    "QwenEdit+",
    "NunQwenEdit+_fp4",
    "NunQwenEdit+_int4",
    "QwenNSFW",
}

RANDOM_QUALITY_TAGS = [
    "masterpiece",
    "best_quality",
    "highres",
    "absurdres",
    "highly_detailed",
]

RANDOM_STYLE_GROUPS = [
    ["anime_style", "illustration", "clean_lineart"],
    ["cinematic_lighting", "depth_of_field", "detailed_background"],
    ["painterly", "soft_shading", "atmospheric_perspective"],
    ["vibrant_colors", "sharp_focus", "rich_details"],
]

RANDOM_SUBJECT_PROFILES = [
    {
        "id": "solo_girl",
        "tags": ["1girl", "solo"],
        "appearance": [
            ["long_hair", "hair_ornament", "blue_eyes"],
            ["short_hair", "bob_cut", "brown_eyes"],
            ["ponytail", "black_hair", "ribbon"],
            ["silver_hair", "green_eyes", "hair_between_eyes"],
        ],
        "outfit": [
            ["school_uniform", "pleated_skirt", "loafers"],
            ["dress", "frills", "detached_sleeves"],
            ["hoodie", "shorts", "sneakers"],
            ["coat", "scarf", "boots"],
        ],
        "action": [
            ["walking", "looking_at_viewer", "gentle_smile"],
            ["sitting", "holding_book", "soft_smile"],
            ["turning_around", "looking_back", "wind"],
            ["standing", "hand_on_chest", "serious"],
        ],
        "lookup_terms": ["school uniform", "long hair", "gentle smile", "walking"],
    },
    {
        "id": "solo_boy",
        "tags": ["1boy", "solo"],
        "appearance": [
            ["short_hair", "messy_hair", "brown_eyes"],
            ["black_hair", "blue_eyes", "hair_between_eyes"],
            ["white_hair", "red_eyes", "serious"],
            ["medium_hair", "green_eyes", "earrings"],
        ],
        "outfit": [
            ["jacket", "shirt", "pants"],
            ["hoodie", "cargo_pants", "sneakers"],
            ["suit", "necktie", "gloves"],
            ["coat", "scarf", "boots"],
        ],
        "action": [
            ["standing", "hands_in_pockets", "looking_at_viewer"],
            ["walking", "looking_away", "wind"],
            ["sitting", "holding_cup", "relaxed"],
            ["running", "dynamic_pose", "determined"],
        ],
        "lookup_terms": ["jacket", "hands in pockets", "dynamic pose", "walking"],
    },
    {
        "id": "duo",
        "tags": ["2girls"],
        "appearance": [
            ["long_hair", "short_hair", "contrasting_hair"],
            ["twin_tails", "bob_cut", "hair_ribbon"],
            ["black_hair", "blonde_hair", "smile"],
            ["white_hair", "brown_hair", "looking_at_each_other"],
        ],
        "outfit": [
            ["school_uniform", "matching_outfit", "pleated_skirt"],
            ["dress", "capelet", "boots"],
            ["jacket", "shorts", "sneakers"],
            ["kimono", "wide_sleeves", "hair_ornament"],
        ],
        "action": [
            ["walking_together", "holding_hands", "smile"],
            ["sitting", "sharing_food", "laughing"],
            ["standing", "looking_at_viewer", "peace_sign"],
            ["running", "dynamic_pose", "motion_blur"],
        ],
        "lookup_terms": ["2girls", "holding hands", "matching outfit", "laughing"],
    },
    {
        "id": "animal_focus",
        "tags": ["animal_focus"],
        "appearance": [
            ["cat", "fluffy", "green_eyes"],
            ["dog", "collar", "wagging_tail"],
            ["fox", "fluffy_tail", "orange_fur"],
            ["rabbit", "long_ears", "soft_fur"],
        ],
        "outfit": [
            ["ribbon", "tiny_hat"],
            ["collar", "bell"],
            ["scarf", "small_bag"],
            ["flower_crown"],
        ],
        "action": [
            ["sitting", "looking_at_viewer"],
            ["sleeping", "curled_up"],
            ["jumping", "motion_blur"],
            ["playing", "pawing_at_object"],
        ],
        "lookup_terms": ["cat", "animal focus", "ribbon", "sitting"],
    },
    {
        "id": "scenery",
        "tags": ["scenery", "no_humans"],
        "appearance": [
            ["wide_shot", "clouds", "distant_mountains"],
            ["river", "stone_path", "trees"],
            ["cityscape", "street_lights", "reflection"],
            ["room", "window", "sunbeam"],
        ],
        "outfit": [[]],
        "action": [
            ["still_water", "floating_leaves"],
            ["wind", "falling_leaves"],
            ["rain", "wet_ground"],
            ["sunlight", "dust_particles"],
        ],
        "lookup_terms": ["scenery", "cityscape", "sunlight", "rain"],
    },
]

RANDOM_SCENE_PROFILES = [
    {
        "id": "rainy_neon_street",
        "tags": ["city", "street", "rain", "wet_ground", "reflection", "neon_lights"],
        "details": [
            ["umbrella", "puddle", "shopfront"],
            ["street_lamp", "traffic_light", "mist"],
            ["raindrops", "window_reflection", "steam"],
            ["crosswalk", "backlighting", "crowd_blur"],
        ],
        "lighting": [
            ["night", "rim_lighting", "glowing_sign"],
            ["blue_light", "pink_light", "backlighting"],
            ["soft_focus", "bokeh", "reflected_light"],
        ],
        "lookup_terms": ["rain", "neon lights", "city street", "reflection"],
    },
    {
        "id": "sunlit_forest_path",
        "tags": ["forest", "path", "trees", "flowers", "sunlight"],
        "details": [
            ["dappled_sunlight", "moss", "wildflowers"],
            ["butterfly", "fallen_leaves", "tree_roots"],
            ["stream", "rocks", "fern"],
            ["wooden_bridge", "mist", "bird"],
        ],
        "lighting": [
            ["morning", "god_rays", "soft_shadows"],
            ["golden_hour", "warm_light", "lens_flare"],
            ["overcast", "diffused_light", "calm"],
        ],
        "lookup_terms": ["forest", "flowers", "sunlight", "mist"],
    },
    {
        "id": "quiet_library",
        "tags": ["library", "bookshelf", "window", "wooden_floor"],
        "details": [
            ["book_stack", "desk", "teacup"],
            ["ladder", "old_books", "curtains"],
            ["paper", "ink_bottle", "dust_particles"],
            ["reading_nook", "lamp", "soft_shadow"],
        ],
        "lighting": [
            ["sunbeam", "warm_light", "soft_focus"],
            ["lamplight", "cozy", "shallow_depth_of_field"],
            ["late_afternoon", "golden_light", "quiet"],
        ],
        "lookup_terms": ["library", "bookshelf", "sunbeam", "book"],
    },
    {
        "id": "seaside_evening",
        "tags": ["ocean", "beach", "waves", "clouds", "horizon"],
        "details": [
            ["sunset", "seafoam", "wet_sand"],
            ["lighthouse", "distant_ship", "seagull"],
            ["pier", "fishing_net", "rope"],
            ["wind", "flowing_clothes", "sparkling_water"],
        ],
        "lighting": [
            ["sunset", "orange_sky", "backlighting"],
            ["blue_hour", "soft_light", "silhouette"],
            ["moonlight", "silver_light", "calm"],
        ],
        "lookup_terms": ["ocean", "sunset", "wind", "waves"],
    },
    {
        "id": "fantasy_ruins",
        "tags": ["ruins", "overgrown", "ancient", "stone", "glowing"],
        "details": [
            ["vines", "broken_pillar", "magic_circle"],
            ["crystal", "floating_particles", "moss"],
            ["statue", "cracked_wall", "flowers"],
            ["archway", "waterfall", "mist"],
        ],
        "lighting": [
            ["mysterious_light", "volumetric_lighting", "blue_glow"],
            ["moonlight", "fog", "soft_shadow"],
            ["sunlight", "god_rays", "atmospheric_perspective"],
        ],
        "lookup_terms": ["ruins", "glowing", "magic circle", "mist"],
    },
    {
        "id": "cozy_room",
        "tags": ["bedroom", "window", "curtains", "plants", "wooden_floor"],
        "details": [
            ["desk", "book", "coffee"],
            ["bed", "blanket", "pillow"],
            ["cat", "chair", "sunbeam"],
            ["poster", "string_lights", "small_shelf"],
        ],
        "lighting": [
            ["morning", "soft_light", "warm_color_palette"],
            ["evening", "lamplight", "cozy"],
            ["rainy_day", "window_light", "muted_colors"],
        ],
        "lookup_terms": ["bedroom", "coffee", "plants", "window"],
    },
]

RANDOM_COMPOSITION_GROUPS = {
    "character": [
        ["cowboy_shot", "eye_level", "depth_of_field"],
        ["upper_body", "from_side", "shallow_depth_of_field"],
        ["full_body", "dynamic_angle", "motion_blur"],
        ["portrait", "center_composition", "detailed_face"],
        ["wide_shot", "rule_of_thirds", "detailed_background"],
    ],
    "scenery": [
        ["wide_shot", "establishing_shot", "atmospheric_perspective"],
        ["panorama", "vanishing_point", "depth_of_field"],
        ["low_angle", "dramatic_perspective", "detailed_background"],
        ["overhead_view", "leading_lines", "sharp_focus"],
    ],
}

RANDOM_ATMOSPHERE_GROUPS = [
    ["calm", "peaceful", "gentle_wind"],
    ["dramatic", "high_contrast", "cinematic_shadow"],
    ["dreamy", "floating_particles", "soft_focus"],
    ["melancholy", "muted_colors", "lonely"],
    ["energetic", "motion_blur", "dynamic_pose"],
]

RANDOM_BAD_LOOKUP_TAGS = {
    "mouth",
    "pose",
    "soft_serve",
    "lighting_cigarette",
    "kiss",
    "softboiled_egg",
    "open_clothes",
    "open_fly",
    "pov",
    "windowboxed",
    "street_fighter",
}

RANDOM_FALLBACK_CHARACTERS = [
    {"character_tag": "hatsune_miku", "copyright_tag": "vocaloid", "subject_hint": "1girl", "score": "100"},
    {"character_tag": "artoria_pendragon_(fate)", "copyright_tag": "fate_(series)", "subject_hint": "1girl", "score": "96"},
    {"character_tag": "ganyu_(genshin_impact)", "copyright_tag": "genshin_impact", "subject_hint": "1girl", "score": "94"},
    {"character_tag": "raiden_shogun", "copyright_tag": "genshin_impact", "subject_hint": "1girl", "score": "92"},
    {"character_tag": "frieren_(sousou_no_frieren)", "copyright_tag": "sousou_no_frieren", "subject_hint": "1girl", "score": "90"},
    {"character_tag": "makima", "copyright_tag": "chainsaw_man", "subject_hint": "1girl", "score": "88"},
    {"character_tag": "hoshino_ai", "copyright_tag": "oshi_no_ko", "subject_hint": "1girl", "score": "86"},
    {"character_tag": "saber_alter", "copyright_tag": "fate/stay_night", "subject_hint": "1girl", "score": "84"},
    {"character_tag": "zhongli_(genshin_impact)", "copyright_tag": "genshin_impact", "subject_hint": "1boy", "score": "82"},
    {"character_tag": "venti_(genshin_impact)", "copyright_tag": "genshin_impact", "subject_hint": "1boy", "score": "80"},
    {"character_tag": "mario", "copyright_tag": "mario_(series)", "subject_hint": "1boy", "score": "78"},
    {"character_tag": "uzumaki_naruto", "copyright_tag": "naruto_(series)", "subject_hint": "1boy", "score": "78"},
    {"character_tag": "monkey_d._luffy", "copyright_tag": "one_piece", "subject_hint": "1boy", "score": "76"},
    {"character_tag": "gojo_satoru", "copyright_tag": "jujutsu_kaisen", "subject_hint": "1boy", "score": "74"},
    {"character_tag": "levi_(shingeki_no_kyojin)", "copyright_tag": "shingeki_no_kyojin", "subject_hint": "1boy", "score": "72"},
    {"character_tag": "edogawa_conan", "copyright_tag": "detective_conan", "subject_hint": "1boy", "score": "70"},
    {"character_tag": "kirito", "copyright_tag": "sword_art_online", "subject_hint": "1boy", "score": "68"},
    {"character_tag": "link", "copyright_tag": "the_legend_of_zelda", "subject_hint": "1boy", "score": "66"},
    {"character_tag": "sakata_gintoki", "copyright_tag": "gintama", "subject_hint": "1boy", "score": "64"},
    {"character_tag": "kaito_(vocaloid)", "copyright_tag": "vocaloid", "subject_hint": "1boy", "score": "62"},
]

RANDOM_PROMPT_NSFW_PROFILES = [
    {
        "id": "dev_nsfw_pair_bedroom",
        "weight": 3,
        "subject_id": "duo",
        "character_chance": 0.55,
        "copyright_chance": 0.35,
        "lighting_chance": 0.25,
        "association_max": 2,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["sex", "vaginal", "cum"],
        "tags": ["1girl", "1boy", "sex", "vaginal"],
        "setting": [
            ["bedroom", "bed", "bed_sheet"],
            ["couch", "indoors", "night"],
            ["shower", "wet", "tile_floor"],
            ["table", "indoors", "lamp"],
        ],
        "pose": [["missionary_position", "legs_up"], ["cowgirl_position", "straddling"]],
        "action": [["sex", "vaginal", "penetration", "grabbing_hips"], ["cowgirl_position", "vaginal", "penetration", "straddling"]],
        "expression": [["orgasm", "open_mouth", "blush"], ["ahegao", "half-closed_eyes", "heavy_breathing"]],
        "body_detail": [["pussy", "penis", "nipples", "wet_pussy"], ["cum", "cum_on_body", "pussy", "penis"]],
        "finish_detail": [["cum", "cum_in_pussy", "cumdrip"], ["after_sex", "cum_on_breasts", "cum_on_body"]],
        "lighting": [["warm_lighting", "depth_of_field"], ["low_light", "rim_lighting"]],
    },
    {
        "id": "dev_nsfw_pair_from_behind",
        "weight": 3,
        "subject_id": "duo",
        "character_chance": 0.55,
        "copyright_chance": 0.35,
        "lighting_chance": 0.25,
        "association_max": 2,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["sex_from_behind", "vaginal", "cum"],
        "tags": ["1girl", "1boy", "sex", "sex_from_behind"],
        "setting": [
            ["bedroom", "bed", "pillow"],
            ["shower", "wet", "tile_wall"],
            ["kitchen", "counter", "indoors"],
            ["car_interior", "night", "window"],
        ],
        "pose": [["sex_from_behind", "on_all_fours"], ["doggystyle", "ass_focus"]],
        "action": [["sex_from_behind", "vaginal", "penetration", "grabbing_hips"], ["doggystyle", "spread_legs", "penetration"]],
        "expression": [["orgasm", "open_mouth", "blush"], ["ahegao", "heavy_breathing", "tears"]],
        "body_detail": [["pussy", "penis", "ass", "wet_pussy"], ["cum", "cum_on_ass", "nipples", "pussy"]],
        "finish_detail": [["cum", "cum_in_pussy", "cumdrip"], ["cum_on_ass", "after_sex", "cum_on_body"]],
        "lighting": [["warm_lighting", "soft_shadow"], ["low_light", "depth_of_field"]],
    },
    {
        "id": "dev_nsfw_pair_oral",
        "weight": 3,
        "subject_id": "duo",
        "character_chance": 0.55,
        "copyright_chance": 0.35,
        "lighting_chance": 0.25,
        "association_max": 2,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["fellatio", "cum"],
        "tags": ["1girl", "1boy", "fellatio"],
        "setting": [
            ["bedroom", "bed", "night"],
            ["indoors", "couch", "lamp"],
            ["office_chair", "desk", "indoors"],
            ["car_interior", "night", "window"],
        ],
        "pose": [["kneeling", "looking_up"], ["sitting", "from_above"]],
        "action": [["fellatio", "penis", "saliva"], ["deepthroat", "saliva", "handjob"]],
        "expression": [["open_mouth", "blush", "half-closed_eyes"], ["ahegao", "tears", "drooling"]],
        "body_detail": [["penis", "saliva"], ["breasts", "nipples"]],
        "finish_detail": [["cum", "cum_on_face", "cum_on_tongue"], ["cum_in_mouth", "after_sex", "drooling"]],
        "lighting": [["warm_lighting", "depth_of_field"], ["soft_lighting", "rim_lighting"]],
    },
    {
        "id": "dev_nsfw_yuri_pair",
        "weight": 2,
        "subject_id": "solo_girl",
        "character_chance": 0.65,
        "copyright_chance": 0.4,
        "lighting_chance": 0.25,
        "association_max": 3,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["yuri", "tribadism", "cunnilingus"],
        "tags": ["2girls", "yuri", "sex"],
        "setting": [
            ["dressing_room", "mirror", "chair"],
            ["shower", "wet", "tile_floor"],
            ["couch", "indoors", "night"],
            ["poolside", "wet", "water"],
        ],
        "pose": [["straddling", "breast_press"], ["lying", "legs_intertwined"], ["sitting", "spread_legs"]],
        "action": [["tribadism", "grinding"], ["cunnilingus", "spread_legs"], ["kissing", "breast_grab"]],
        "expression": [["orgasm", "open_mouth", "blush"], ["ahegao", "heavy_breathing"], ["teasing_smile", "half-closed_eyes"]],
        "body_detail": [["pussy", "thighs"], ["nipples", "breasts"], ["wet_pussy", "female_ejaculation"]],
        "finish_detail": [["female_ejaculation", "cum_on_body"], ["after_sex", "messy_hair"], ["wet_pussy", "pussy_juice"]],
        "lighting": [["soft_lighting", "depth_of_field"], ["rim_lighting", "wet"]],
    },
    {
        "id": "dev_nsfw_toy_private",
        "weight": 3,
        "subject_id": "solo_girl",
        "character_chance": 0.65,
        "copyright_chance": 0.4,
        "lighting_chance": 0.25,
        "association_max": 2,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["sex_toy", "vibrator", "orgasm"],
        "tags": ["1girl", "solo", "nude", "sex_toy"],
        "setting": [
            ["bedroom", "bed", "pillow"],
            ["bathroom", "mirror", "tile_floor"],
            ["dressing_room", "mirror", "chair"],
            ["couch", "indoors", "night"],
        ],
        "pose": [["lying", "spread_legs"], ["sitting", "legs_apart"]],
        "action": [["vibrator", "masturbation", "hand_between_legs"], ["dildo", "penetration", "spread_legs"]],
        "expression": [["orgasm", "open_mouth", "blush"], ["ahegao", "heavy_breathing", "drooling"]],
        "body_detail": [["pussy", "wet_pussy"], ["nipples", "pubic_hair"]],
        "finish_detail": [["cum", "cum_on_body", "cumdrip"], ["after_sex", "cum_on_thighs", "wet_pussy"]],
        "lighting": [["soft_lighting", "depth_of_field"], ["warm_lighting", "rim_lighting"]],
    },
    {
        "id": "dev_nsfw_exposure_outfit",
        "weight": 3,
        "subject_id": "solo_girl",
        "character_chance": 0.7,
        "copyright_chance": 0.45,
        "lighting_chance": 0.2,
        "association_max": 3,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["clothes_lift", "upskirt", "no_panties"],
        "tags": ["1girl", "solo", "clothes_lift", "no_panties"],
        "setting": [
            ["dressing_room", "mirror", "chair"],
            ["classroom", "desk", "window"],
            ["backstage", "curtains", "spotlight"],
            ["stairwell", "indoors", "railing"],
        ],
        "pose": [["standing", "skirt_lift"], ["sitting", "spread_legs"], ["bent_over", "looking_back"]],
        "action": [["clothes_lift", "flashing"], ["upskirt", "pantyshot"], ["shirt_lift", "no_bra"]],
        "expression": [["embarrassed", "blush", "open_mouth"], ["teasing_smile", "looking_at_viewer"], ["heavy_breathing", "half-closed_eyes"]],
        "body_detail": [["pussy", "cameltoe"], ["nipples", "underboob"], ["thighs", "ass"]],
        "finish_detail": [["wet_pussy", "pussy_juice"], ["cum", "cum_on_clothes"], ["after_sex", "disheveled_clothes"]],
        "lighting": [["soft_lighting", "depth_of_field"], ["spotlight", "dark_background"]],
    },
    {
        "id": "dev_nsfw_wet_see_through",
        "weight": 3,
        "subject_id": "solo_girl",
        "character_chance": 0.65,
        "copyright_chance": 0.4,
        "lighting_chance": 0.25,
        "association_max": 3,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["see-through_clothes", "wet_clothes", "nipples"],
        "tags": ["1girl", "solo", "wet_clothes", "see-through_clothes"],
        "setting": [
            ["shower", "wet", "tile_wall"],
            ["rain", "wet", "night"],
            ["poolside", "wet", "water"],
            ["bathroom", "mirror", "steam"],
        ],
        "pose": [["standing", "from_side"], ["sitting", "spread_legs"], ["leaning_forward", "looking_at_viewer"]],
        "action": [["see-through_clothes", "clothes_lift"], ["wet_shirt", "no_bra"], ["panties_aside", "hand_between_legs"]],
        "expression": [["blush", "open_mouth", "heavy_breathing"], ["orgasm", "half-closed_eyes"], ["teasing_smile", "looking_at_viewer"]],
        "body_detail": [["nipples", "erect_nipples"], ["pussy", "wet_pussy"], ["underboob", "thighs"]],
        "finish_detail": [["cum", "cum_on_body"], ["wet_pussy", "pussy_juice"], ["after_sex", "messy_hair"]],
        "lighting": [["steam", "diffused_light"], ["backlighting", "rim_lighting"]],
    },
    {
        "id": "dev_nsfw_after_scene",
        "weight": 2,
        "subject_id": "solo_girl",
        "character_chance": 0.65,
        "copyright_chance": 0.4,
        "lighting_chance": 0.25,
        "association_max": 3,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["after_sex", "cum", "disheveled_clothes"],
        "tags": ["1girl", "solo", "after_sex", "cum"],
        "setting": [
            ["couch", "indoors", "night"],
            ["car_interior", "window", "night"],
            ["dressing_room", "mirror", "chair"],
            ["bedroom", "bed", "pillow"],
        ],
        "pose": [["lying", "spread_legs"], ["sitting", "legs_apart"], ["reclining", "looking_at_viewer"]],
        "action": [["after_sex", "disheveled_clothes"], ["clothes_lift", "cum"], ["panties_aside", "cumdrip"]],
        "expression": [["afterglow", "half-closed_eyes", "blush"], ["heavy_breathing", "open_mouth"], ["tired", "messy_hair"]],
        "body_detail": [["cum_on_body", "pussy"], ["cum_on_breasts", "nipples"], ["wet_pussy", "thighs"]],
        "finish_detail": [["cum", "cumdrip"], ["cum_on_clothes", "messy_hair"], ["after_sex", "pussy_juice"]],
        "lighting": [["low_light", "soft_shadow"], ["warm_lighting", "depth_of_field"]],
    },
    {
        "id": "dev_nsfw_cosplay_private",
        "weight": 2,
        "subject_id": "solo_girl",
        "character_chance": 0.75,
        "copyright_chance": 0.45,
        "lighting_chance": 0.2,
        "association_max": 3,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["cosplay", "no_panties", "clothes_lift"],
        "tags": ["1girl", "solo", "cosplay", "no_panties"],
        "setting": [
            ["dressing_room", "mirror", "clothes_rack"],
            ["bedroom", "mirror", "night"],
            ["photo_studio", "curtains", "spotlight"],
            ["backstage", "curtains", "chair"],
        ],
        "pose": [["standing", "clothes_lift"], ["sitting", "spread_legs"], ["kneeling", "looking_at_viewer"]],
        "action": [["clothes_lift", "panties_aside"], ["shirt_lift", "no_bra"], ["breast_grab", "skirt_lift"]],
        "expression": [["teasing_smile", "blush"], ["orgasm", "open_mouth"], ["ahegao", "heavy_breathing"]],
        "body_detail": [["pussy", "nipples"], ["cameltoe", "thighs"], ["wet_pussy", "underboob"]],
        "finish_detail": [["cum", "cum_on_body"], ["wet_pussy", "pussy_juice"], ["after_sex", "disheveled_clothes"]],
        "lighting": [["spotlight", "dark_background"], ["soft_lighting", "depth_of_field"]],
    },
    {
        "id": "dev_nsfw_lingerie_private",
        "weight": 1,
        "subject_id": "solo_girl",
        "character_chance": 0.65,
        "copyright_chance": 0.4,
        "lighting_chance": 0.2,
        "association_max": 2,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["lingerie", "orgasm", "wet_pussy"],
        "tags": ["1girl", "solo", "lingerie", "no_panties"],
        "setting": [
            ["bedroom", "bed", "curtains"],
            ["dressing_room", "mirror", "chair"],
            ["couch", "indoors", "curtains"],
            ["balcony", "curtains", "night"],
        ],
        "pose": [["lying", "spread_legs"], ["sitting", "legs_apart"], ["standing", "clothes_lift"]],
        "action": [["masturbation", "hand_between_legs", "spread_legs"], ["panties_aside", "wet_pussy"], ["breast_grab", "no_bra"]],
        "expression": [["orgasm", "open_mouth", "blush"], ["ahegao", "half-closed_eyes", "heavy_breathing"]],
        "body_detail": [["pussy", "nipples"], ["wet_pussy", "thighs"]],
        "finish_detail": [["cum", "cum_on_body", "cumdrip"], ["after_sex", "cum_on_breasts", "wet_pussy"]],
        "lighting": [["soft_lighting", "depth_of_field"], ["warm_lighting", "rim_lighting"]],
    },
    {
        "id": "dev_nsfw_onsen",
        "weight": 2,
        "subject_id": "solo_girl",
        "character_chance": 0.65,
        "copyright_chance": 0.4,
        "lighting_chance": 0.2,
        "association_max": 2,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["nude", "wet_pussy", "orgasm"],
        "tags": ["1girl", "solo", "nude", "wet"],
        "setting": [["onsen", "steam", "water"], ["bath", "wet", "towel"], ["shower", "wet", "tile_wall"]],
        "pose": [["sitting", "spread_legs"], ["lying", "legs_apart"]],
        "action": [["masturbation", "fingering", "spread_legs"], ["touching_self", "wet_pussy", "legs_apart"], ["breast_grab", "legs_apart"]],
        "expression": [["orgasm", "open_mouth", "blush"], ["ahegao", "half-closed_eyes", "heavy_breathing"]],
        "body_detail": [["pussy", "nipples"], ["wet_pussy", "pubic_hair"]],
        "finish_detail": [["cum", "cum_on_body", "cumdrip"], ["after_sex", "cum_on_thighs", "wet_pussy"]],
        "lighting": [["steam", "soft_lighting"], ["mist", "diffused_light"]],
    },
    {
        "id": "dev_nsfw_lounge",
        "weight": 2,
        "subject_id": "solo_girl",
        "character_chance": 0.65,
        "copyright_chance": 0.4,
        "lighting_chance": 0.2,
        "association_max": 2,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["topless", "breast_grab", "orgasm"],
        "tags": ["1girl", "solo", "topless", "breast_grab"],
        "setting": [["couch", "fireplace", "curtains"], ["chair", "indoors", "lamp"], ["table", "indoors", "night"]],
        "pose": [["reclining", "spread_legs"], ["sitting", "legs_apart"]],
        "action": [["breast_grab", "hand_between_legs"], ["panties_aside", "spread_legs", "touching_self"], ["clothes_lift", "no_bra"]],
        "expression": [["orgasm", "open_mouth", "blush"], ["ahegao", "half-closed_eyes", "heavy_breathing"]],
        "body_detail": [["nipples", "areolae"], ["pussy", "thighs"]],
        "finish_detail": [["cum", "cum_on_breasts", "cumdrip"], ["after_sex", "cum_on_body", "wet_pussy"]],
        "lighting": [["warm_light", "soft_shadow"], ["low_light", "depth_of_field"]],
    },
    {
        "id": "dev_nsfw_stage",
        "weight": 1,
        "subject_id": "solo_girl",
        "character_chance": 0.55,
        "copyright_chance": 0.3,
        "lighting_chance": 0.15,
        "association_max": 2,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["no_bra", "clothes_lift", "orgasm"],
        "tags": ["1girl", "solo", "no_bra", "clothes_lift"],
        "setting": [["stage", "spotlight", "curtains"], ["dressing_room", "mirror", "spotlight"]],
        "pose": [["standing", "spread_legs"], ["sitting", "legs_apart"]],
        "action": [["clothes_lift", "breast_grab", "spread_legs"], ["panties_aside", "hand_between_legs", "spread_legs"]],
        "expression": [["orgasm", "open_mouth", "heavy_breathing"], ["ahegao", "half-closed_eyes", "blush"]],
        "body_detail": [["nipples", "underboob"], ["pussy", "cameltoe"]],
        "finish_detail": [["cum", "cum_on_body", "cumdrip"], ["after_sex", "cum_on_breasts", "wet_pussy"]],
        "lighting": [["spotlight", "dramatic_lighting"], ["rim_lighting", "dark_background"]],
    },
    {
        "id": "dev_nsfw_striptease_photo",
        "weight": 2,
        "subject_id": "solo_girl",
        "character_chance": 0.7,
        "copyright_chance": 0.45,
        "lighting_chance": 0.25,
        "association_max": 3,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["striptease", "nude", "no_panties"],
        "tags": ["1girl", "solo", "striptease", "no_panties"],
        "setting": [
            ["photo_studio", "curtains", "spotlight"],
            ["dressing_room", "mirror", "clothes_rack"],
            ["balcony", "night", "curtains"],
            ["office_chair", "desk", "indoors"],
        ],
        "pose": [["standing", "clothes_lift"], ["sitting", "spread_legs"], ["from_behind", "looking_back"]],
        "action": [["shirt_lift", "no_bra"], ["skirt_lift", "panties_aside"], ["breast_grab", "clothes_lift"]],
        "expression": [["teasing_smile", "looking_at_viewer"], ["orgasm", "open_mouth"], ["embarrassed", "blush"]],
        "body_detail": [["pussy", "thighs"], ["nipples", "underboob"], ["wet_pussy", "cameltoe"]],
        "finish_detail": [["wet_pussy", "pussy_juice"], ["cum", "cum_on_clothes"], ["after_sex", "disheveled_clothes"]],
        "lighting": [["spotlight", "dark_background"], ["soft_lighting", "depth_of_field"]],
    },
]

RANDOM_PROMPT_ADULT_SLOT_MAP = {
    "scene": "setting",
    "camera": "camera",
    "pose_action": "pose",
    "expression": "expression",
    "clothing": "clothing",
    "body_detail": "body_detail",
    "prop": "prop",
    "style_light": "lighting",
}

RANDOM_PROMPT_ADULT_SLOT_ORDER = (
    "setting",
    "camera",
    "pose",
    "expression",
    "clothing",
    "body_detail",
    "prop",
    "lighting",
)

RANDOM_PROMPT_ADULT_BLOCKED_EXACT_TAGS = set()

RANDOM_PROMPT_ADULT_BLOCKED_FRAGMENTS = (
    "child", "children", "loli", "shota", "minor", "kindergarten", "elementary",
    "watermark", "signature", "artist", "commentary", "request", "text", "english_text",
    "mosaic", "censored",
)

RANDOM_PROMPT_ADULT_CHARACTER_BLOCK_FRAGMENTS = (
    "child", "children", "loli", "shota", "minor", "kindergarten",
    "elementary", "klee", "qiqi", "yaoyao", "paimon", "edogawa_conan",
    "detective_conan",
)

RANDOM_PROMPT_ADULT_NEGATIVE_MIN_SCORE = 2500.0
RANDOM_PROMPT_ADULT_NEGATIVE_MAX_LIFT = 0.45


def _clean_text(value):
    return str(value or "").strip()


def _clean_lang(value):
    lang = _clean_text(value).lower()
    return "en" if lang.startswith("en") else "cn"


def _safe_prompt_file_name(preset_name):
    name = _clean_text(preset_name)
    if not name:
        return ""
    name = os.path.basename(name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().strip(".")
    return name


def _preset_json_path(preset_name):
    safe = _safe_prompt_file_name(preset_name)
    if not safe:
        return ""
    return os.path.join(ROOT_DIR, "presets", f"{safe}.json")


def _load_preset_scene_frontend(preset_name):
    path = _preset_json_path(preset_name)
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    default_engine = data.get("default_engine") if isinstance(data, dict) else {}
    scene_frontend = default_engine.get("scene_frontend") if isinstance(default_engine, dict) else {}
    return scene_frontend if isinstance(scene_frontend, dict) else {}


def _scene_value_candidates(value):
    if isinstance(value, dict):
        return [_clean_text(item) for item in value.values() if _clean_text(item)]
    if isinstance(value, (list, tuple, set)):
        return [_clean_text(item) for item in value if _clean_text(item)]
    clean = _clean_text(value)
    return [clean] if clean else []


def _scene_director_capability(scene_frontend):
    capability = scene_frontend.get("director_capability") if isinstance(scene_frontend, dict) else {}
    return capability if isinstance(capability, dict) else {}


def _has_i2v_marker(value):
    clean = _clean_text(value).lower()
    if not clean or "ai2v" in clean or "ia2v" in clean:
        return False
    normalized = re.sub(r"[^a-z0-9]+", "_", clean).strip("_")
    parts = [part for part in normalized.split("_") if part]
    return "(i2v)" in clean or "i2v" in parts or normalized.endswith("i2v")


def _has_image_to_video_phrase(value):
    clean = _clean_text(value).lower().replace("_", " ").replace("-", " ")
    return "image to video" in clean


def _scene_prompt_supports_shared_image_to_video(preset_name, scene_frontend, task_methods, capability):
    image_policy = _clean_text(capability.get("image_policy")).lower()
    video_policy = _clean_text(capability.get("video_policy")).lower()
    audio_policy = _clean_text(capability.get("audio_policy")).lower()
    if image_policy != "required" or video_policy not in {"", "forbidden"} or audio_policy not in {"", "forbidden"}:
        return False

    image_modes = [item.lower() for item in _scene_value_candidates(capability.get("image_modes"))]
    has_image_input = _safe_int(capability.get("max_images"), 0) > 0 or any(
        mode in {"first_frame", "first_last", "reference_set"} for mode in image_modes
    )
    if not has_image_input:
        return False

    marker_values = [preset_name, scene_frontend.get("theme_title")]
    marker_values.extend(task_methods)
    marker_values.extend(_scene_value_candidates(scene_frontend.get("theme")))
    return any(_has_i2v_marker(item) or _has_image_to_video_phrase(item) for item in marker_values)


def _scene_prompt_shared_keys(preset_name):
    keys = []
    if _safe_prompt_file_name(preset_name) in IMAGE_EDIT_SHARED_PRESETS:
        keys.append("image_edit")

    scene_frontend = _load_preset_scene_frontend(preset_name)
    if not scene_frontend:
        return keys
    task_methods = [item.lower() for item in _scene_value_candidates(scene_frontend.get("task_method"))]
    capability = _scene_director_capability(scene_frontend)
    image_policy = _clean_text(capability.get("image_policy")).lower()
    video_policy = _clean_text(capability.get("video_policy")).lower()
    audio_policy = _clean_text(capability.get("audio_policy")).lower()
    if _scene_prompt_supports_shared_image_to_video(preset_name, scene_frontend, task_methods, capability):
        keys.append("image_to_video")
    no_media_input = (
        image_policy in {"", "forbidden"}
        and video_policy in {"", "forbidden"}
        and audio_policy in {"", "forbidden"}
    )
    if no_media_input and any("t2v" in method for method in task_methods):
        keys.append("text_to_video")
    return keys


def _candidate_prompt_files(preset_name):
    safe = _safe_prompt_file_name(preset_name)
    result = []
    if safe:
        result.append(os.path.join(RECOMMENDATIONS_DIR, f"{safe}.csv"))
    for key in _scene_prompt_shared_keys(preset_name):
        shared_name = SHARED_RECOMMENDATION_FILES.get(key)
        if shared_name:
            result.append(os.path.join(RECOMMENDATIONS_DIR, shared_name))
    result.append(os.path.join(RECOMMENDATIONS_DIR, "_default.csv"))
    seen = set()
    unique = []
    for path in result:
        if path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            unique.append(path)
    return unique


def _relative_prompt_file(path):
    return os.path.relpath(path, ROOT_DIR).replace("\\", "/")


def _read_prompt_rows(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(line for line in f if not line.lstrip().startswith("#"))
        for index, row in enumerate(reader):
            if not isinstance(row, dict):
                continue
            prompt = _clean_text(row.get("prompt"))
            if not prompt:
                continue
            target = PROMPT_TARGETS.get(_clean_text(row.get("target")).lower(), "positive_prompt")
            mode = _clean_text(row.get("mode")).lower()
            if mode not in PROMPT_MODES:
                mode = "replace"
            item = {
                "id": _clean_text(row.get("id")) or f"{os.path.basename(path)}:{index + 1}",
                "scene_theme": _clean_text(row.get("scene_theme")) or "*",
                "target": target,
                "mode": mode,
                "title_en": _clean_text(row.get("title_en")),
                "title_cn": _clean_text(row.get("title_cn")),
                "prompt": prompt,
                "seed_terms": _split_terms(row.get("seed_terms")),
                "weight": _safe_int(row.get("weight"), 100),
                "source_file": _relative_prompt_file(path),
            }
            rows.append(item)
    return rows


def _safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def _split_terms(value):
    terms = []
    for item in re.split(r"[|,;]", str(value or "")):
        clean = item.strip()
        if clean and clean not in terms:
            terms.append(clean)
    return terms


def _scene_theme_matches(row_theme, scene_theme):
    wanted = _clean_text(scene_theme).lower()
    current = _clean_text(row_theme).lower()
    if not current or current == "*":
        return True
    if not wanted:
        return True
    return current == wanted


def _recommendation_title(row, lang):
    if _clean_lang(lang) == "en":
        return row.get("title_en") or row.get("title_cn") or row.get("id")
    return row.get("title_cn") or row.get("title_en") or row.get("id")


def _dedupe_prompt_rows(rows):
    result = []
    seen_ids = set()
    seen_prompts = set()
    for row in rows:
        item_id = _clean_text(row.get("id")).lower()
        prompt_key = re.sub(r"\s+", "", _clean_text(row.get("prompt")).lower())
        if item_id and item_id in seen_ids:
            continue
        if prompt_key and prompt_key in seen_prompts:
            continue
        if item_id:
            seen_ids.add(item_id)
        if prompt_key:
            seen_prompts.add(prompt_key)
        result.append(row)
    return result


def list_prompt_recommendations(preset_name, scene_theme="", lang="cn", limit=12):
    rows = []
    for path in _candidate_prompt_files(preset_name):
        rows.extend(_read_prompt_rows(path))
    rows = [row for row in rows if _scene_theme_matches(row.get("scene_theme"), scene_theme)]
    rows = _dedupe_prompt_rows(rows)
    rows.sort(key=lambda row: (-_safe_int(row.get("weight"), 100), str(row.get("id") or "")))
    max_limit = max(1, min(_safe_int(limit, 12), 50))
    preset = _clean_text(preset_name)
    return [
        {
            **row,
            "title": _recommendation_title(row, lang),
            "preset": preset,
        }
        for row in rows[:max_limit]
    ]


def recommendation_payload(preset_name, scene_theme="", lang="cn", limit=12):
    candidate_files = [_relative_prompt_file(path) for path in _candidate_prompt_files(preset_name)]
    return {
        "ok": True,
        "preset": _clean_text(preset_name),
        "scene_theme": _clean_text(scene_theme),
        "items": list_prompt_recommendations(preset_name, scene_theme=scene_theme, lang=lang, limit=limit),
        "source_dir": os.path.relpath(RECOMMENDATIONS_DIR, ROOT_DIR).replace("\\", "/"),
        "source_files": candidate_files,
    }


def _safe_danbooru_tag(tag):
    return canvas_danbooru_service._canvas_prompt_safe_danbooru_tag(tag)


def _prompt_lookup_norm(value):
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _read_csv_dict_rows(path):
    if not path or not os.path.isfile(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _env_flag_enabled(name):
    return _clean_text(os.environ.get(name)).lower() in {"1", "true", "yes", "on"}


def _developer_random_prompt_nsfw_enabled():
    return _env_flag_enabled(RANDOM_PROMPT_NSFW_ENV)


def _random_prompt_nsfw_requested(prompt_text):
    prompt = _clean_text(prompt_text)
    return bool(re.match(r"^nsfw(?:$|[\s,.;:!?，。；：！？、|/\\()\[\]{}_-])", prompt, re.I))


def _random_prompt_adult_tag_blocked(tag, character=False):
    clean = _prompt_lookup_norm(tag)
    if not clean:
        return True
    if len(clean) > 56 or clean.count("_") > 6:
        return True
    if clean in RANDOM_PROMPT_ADULT_BLOCKED_EXACT_TAGS:
        return True
    fragments = RANDOM_PROMPT_ADULT_CHARACTER_BLOCK_FRAGMENTS if character else RANDOM_PROMPT_ADULT_BLOCKED_FRAGMENTS
    return any(fragment in clean for fragment in fragments)


def _random_prompt_adult_tag_allowed(tag):
    clean = _prompt_lookup_norm(tag)
    if _random_prompt_adult_tag_blocked(clean):
        return False
    if clean in RANDOM_BAD_LOOKUP_TAGS:
        return False
    if clean in {"male_focus", "female_focus", "solo_focus"}:
        return False
    return True


def _random_prompt_adult_slot_rows():
    global _random_prompt_adult_slot_cache
    if _random_prompt_adult_slot_cache is not None:
        return _random_prompt_adult_slot_cache
    by_trigger = {}
    for row in _read_csv_dict_rows(RANDOM_PROMPT_ADULT_SLOTS_FILE):
        trigger = _prompt_lookup_norm(row.get("trigger_tag"))
        related = _prompt_lookup_norm(row.get("related_tag"))
        source_slot = _clean_text(row.get("slot")).lower()
        slot = RANDOM_PROMPT_ADULT_SLOT_MAP.get(source_slot)
        if not trigger or not related or not slot:
            continue
        if not _random_prompt_adult_tag_allowed(related):
            continue
        item = {
            "trigger": trigger,
            "related": related,
            "slot": slot,
            "source_slot": source_slot,
            "support": _safe_int(row.get("support"), 0),
            "lift": _safe_float(row.get("lift"), 0.0),
            "score": _safe_float(row.get("score"), 0.0),
        }
        by_trigger.setdefault(trigger, []).append(item)
    for rows in by_trigger.values():
        rows.sort(key=lambda item: (-item["score"], -item["support"], item["related"]))
    _random_prompt_adult_slot_cache = by_trigger
    return by_trigger


def _random_prompt_adult_negative_pairs():
    global _random_prompt_adult_negative_cache
    if _random_prompt_adult_negative_cache is not None:
        return _random_prompt_adult_negative_cache
    pairs = set()
    for row in _read_csv_dict_rows(RANDOM_PROMPT_ADULT_NEGATIVE_FILE):
        left = _prompt_lookup_norm(row.get("trigger_tag"))
        right = _prompt_lookup_norm(row.get("related_tag"))
        if not left or not right or left == right:
            continue
        score = _safe_float(row.get("negative_score"), 0.0)
        lift = _safe_float(row.get("lift"), 1.0)
        if score >= RANDOM_PROMPT_ADULT_NEGATIVE_MIN_SCORE and lift <= RANDOM_PROMPT_ADULT_NEGATIVE_MAX_LIFT:
            pairs.add(tuple(sorted((left, right))))
    _random_prompt_adult_negative_cache = pairs
    return pairs


def _random_prompt_adult_negative_conflicts(tag, anchors):
    clean = _prompt_lookup_norm(tag)
    if not clean:
        return True
    pairs = _random_prompt_adult_negative_pairs()
    for anchor in anchors or ():
        anchor_norm = _prompt_lookup_norm(anchor)
        if anchor_norm and anchor_norm != clean and tuple(sorted((anchor_norm, clean))) in pairs:
            return True
    return False


def _random_prompt_adult_stats_tags(trigger_tags, current_tags, rng, max_count=6, allowed_slots=None):
    by_trigger = _random_prompt_adult_slot_rows()
    if not by_trigger:
        return []
    triggers = []
    for tag in list(trigger_tags or []) + list(current_tags or []):
        clean = _prompt_lookup_norm(tag)
        if clean and clean in by_trigger and clean not in triggers:
            triggers.append(clean)
    if not triggers:
        return []

    current_norms = {_prompt_lookup_norm(tag) for tag in current_tags if _prompt_lookup_norm(tag)}
    candidates_by_slot = {}
    allowed_slot_set = {_clean_text(item).lower() for item in allowed_slots or [] if _clean_text(item)}
    for trigger in triggers:
        for row in by_trigger.get(trigger, [])[:80]:
            related = row.get("related")
            slot = _clean_text(row.get("slot")).lower()
            if allowed_slot_set and slot not in allowed_slot_set:
                continue
            if not related or related in current_norms:
                continue
            candidates_by_slot.setdefault(slot, []).append(row)

    picked = []
    picked_norms = set()
    anchors = set(current_norms)
    for slot in RANDOM_PROMPT_ADULT_SLOT_ORDER:
        if len(picked) >= max_count:
            break
        candidates = []
        seen = set()
        for row in candidates_by_slot.get(slot, []):
            related = row.get("related")
            if not related or related in seen or related in picked_norms:
                continue
            if _random_prompt_adult_negative_conflicts(related, anchors.union(picked_norms)):
                continue
            seen.add(related)
            candidates.append(row)
        if not candidates:
            continue
        pool = candidates[: min(len(candidates), 10)]
        row = rng.choice(pool)
        related = row.get("related")
        if related:
            picked.append(_safe_danbooru_tag(related))
            picked_norms.add(related)
    return picked[:max(1, max_count)]


def _adult_character_row_allowed(row):
    return not (
        _random_prompt_adult_tag_blocked(row.get("character_tag"), character=True)
        or _random_prompt_adult_tag_blocked(row.get("copyright_tag"), character=True)
    )


def _pick_adult_random_character_tags(rng, subject_id, chance=1.0, copyright_chance=1.0):
    chance = max(0.0, min(1.0, _safe_float(chance, 1.0)))
    if chance < 1.0 and rng.random() > chance:
        return []
    rows = [
        row for row in _random_prompt_character_rows()
        if _character_subject_matches(row, subject_id) and _adult_character_row_allowed(row)
    ]
    if not rows:
        rows = [row for row in _random_prompt_character_rows() if _adult_character_row_allowed(row)]
    if not rows:
        return []
    top = rows[: min(len(rows), RANDOM_CHARACTER_SAMPLE_POOL)]
    picked = rng.choice(top)
    tags = [picked.get("character_tag")]
    copyright_chance = max(0.0, min(1.0, _safe_float(copyright_chance, 1.0)))
    if picked.get("copyright_tag") and rng.random() <= copyright_chance:
        tags.append(picked.get("copyright_tag"))
    return [tag for tag in tags if tag]


def _random_prompt_noise_tags():
    global _random_prompt_noise_cache
    if _random_prompt_noise_cache is not None:
        return _random_prompt_noise_cache
    noise = set()
    for row in _read_csv_dict_rows(RANDOM_PROMPT_NOISE_FILE):
        tag = _prompt_lookup_norm(row.get("tag"))
        reason = _clean_text(row.get("reason")).lower()
        if tag and reason in {"adult", "artist", "copyright", "bad_pattern", "low_value", "unwanted"}:
            noise.add(tag)
    _random_prompt_noise_cache = noise
    return noise


def _random_prompt_association_rows():
    global _random_prompt_association_cache
    if _random_prompt_association_cache is not None:
        return _random_prompt_association_cache
    by_trigger = {}
    for row in _read_csv_dict_rows(RANDOM_PROMPT_ASSOCIATIONS_FILE):
        trigger = _prompt_lookup_norm(row.get("trigger"))
        related = _prompt_lookup_norm(row.get("related"))
        slot = _clean_text(row.get("slot")).lower()
        if not trigger or not related or not slot:
            continue
        item = {
            "trigger": trigger,
            "related": related,
            "slot": slot,
            "support": _safe_int(row.get("support"), 0),
            "lift": _safe_float(row.get("lift"), 0.0),
            "score": _safe_float(row.get("score"), 0.0),
        }
        by_trigger.setdefault(trigger, []).append(item)
    for rows in by_trigger.values():
        rows.sort(key=lambda item: (-item["score"], -item["support"], item["related"]))
    _random_prompt_association_cache = by_trigger
    return by_trigger


def _random_prompt_character_rows():
    global _random_prompt_character_cache
    if _random_prompt_character_cache is not None:
        return _random_prompt_character_cache
    csv_rows = _read_csv_dict_rows(RANDOM_PROMPT_CHARACTERS_FILE)
    source_rows = list(csv_rows) + list(RANDOM_FALLBACK_CHARACTERS) if csv_rows else RANDOM_FALLBACK_CHARACTERS
    rows = []
    seen = set()
    for row in source_rows:
        character = _safe_danbooru_tag(row.get("character_tag"))
        copyright_tag = _safe_danbooru_tag(row.get("copyright_tag"))
        if not character:
            continue
        key = (character.lower(), copyright_tag.lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "character_tag": character,
                "copyright_tag": copyright_tag,
                "subject_hint": _prompt_lookup_norm(row.get("subject_hint")),
                "score": _safe_float(row.get("score"), 0.0),
            }
        )
    rows.sort(key=lambda item: (-item["score"], item["character_tag"], item["copyright_tag"]))
    _random_prompt_character_cache = rows
    return rows


def _prompt_lookup_tag_is_visual(tag):
    raw = str(tag or "").strip().lower()
    if raw.startswith("@") or "\\" in raw:
        return False
    if re.search(r"[,/&!:\\]|\(|\)|\[|\]", raw):
        return False
    clean = _prompt_lookup_norm(tag)
    if not clean or clean in RANDOM_BAD_LOOKUP_TAGS or clean in _random_prompt_noise_tags() or "kiss" in clean:
        return False
    if len(clean) > 48:
        return False
    if clean.count("_") > 5:
        return False
    return True


def _prompt_lookup_relevance(tag, query, fallback_tags=None):
    tag_norm = _prompt_lookup_norm(tag)
    query_norm = _prompt_lookup_norm(query)
    fallback_norms = {_prompt_lookup_norm(item) for item in fallback_tags or []}
    if not tag_norm or not query_norm:
        return 0
    if tag_norm in fallback_norms:
        return 120
    if tag_norm == query_norm:
        return 110
    if "_" not in query_norm:
        return 0
    if tag_norm.startswith(f"{query_norm}_"):
        suffix_parts = [part for part in tag_norm[len(query_norm) + 1:].split("_") if part]
        if len(suffix_parts) <= 1:
            return 92
        return 0
    if query_norm.startswith(f"{tag_norm}_") and len(tag_norm) >= max(6, int(len(query_norm) * 0.7)):
        return 76
    query_parts = [part for part in query_norm.split("_") if len(part) >= 3]
    tag_parts = tag_norm.split("_")
    if len(query_parts) >= 2 and len(tag_parts) <= len(query_parts) + 1 and all(part in tag_parts for part in query_parts):
        return 72
    return 0


def _lookup_prompt_tags(query, fallback_tags=None, source_mode="all", rng=None, max_count=1):
    fallbacks = [_safe_danbooru_tag(item) for item in fallback_tags or [] if _safe_danbooru_tag(item)]
    try:
        matches = canvas_danbooru_service._canvas_lookup_danbooru_tags(
            query,
            limit=12,
            source_mode=source_mode,
        )
    except Exception:
        matches = []
    candidates = []
    for item in matches or []:
        tag = _safe_danbooru_tag(item.get("tag") if isinstance(item, dict) else item)
        category = _clean_text(item.get("category") if isinstance(item, dict) else "").lower()
        if category in {"artist", "character", "copyright"}:
            continue
        if not tag or not _prompt_lookup_tag_is_visual(tag):
            continue
        relevance = _prompt_lookup_relevance(tag, query, fallback_tags=fallbacks)
        if relevance <= 0:
            continue
        count = _safe_int(item.get("count"), 0) if isinstance(item, dict) else 0
        candidates.append((relevance, count, tag))
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
    if candidates and rng is not None:
        top = candidates[: min(len(candidates), 5)]
        rng.shuffle(top)
        candidates = top + candidates[min(len(candidates), 5):]
    result = []
    for _relevance, _count, tag in candidates:
        if tag not in result:
            result.append(tag)
        if len(result) >= max_count:
            break
    for tag in fallbacks:
        if tag and tag not in result:
            result.append(tag)
        if len(result) >= max_count:
            break
    return result[:max(1, max_count)]


def _random_prompt_association_tags(current_tags, rng, max_count=5):
    by_trigger = _random_prompt_association_rows()
    if not by_trigger:
        return []
    current_norms = {_prompt_lookup_norm(tag) for tag in current_tags if _prompt_lookup_norm(tag)}
    picked = []
    picked_slots = set()
    candidates = []
    for trigger in current_norms:
        for row in by_trigger.get(trigger, [])[:18]:
            related = row.get("related")
            slot = row.get("slot")
            if not _random_prompt_related_tag_allowed(related, current_norms):
                continue
            candidates.append(row)
    rng.shuffle(candidates)
    candidates.sort(key=lambda item: (-item.get("score", 0.0), -item.get("support", 0), item.get("related", "")))
    for row in candidates:
        related = row.get("related")
        slot = row.get("slot")
        if not related or related in current_norms or related in picked:
            continue
        if slot in picked_slots and len(picked_slots) < 4:
            continue
        picked.append(_safe_danbooru_tag(related))
        picked_slots.add(slot)
        if len(picked) >= max_count:
            break
    return picked


def _random_prompt_related_tag_allowed(related, current_norms):
    related_norm = _prompt_lookup_norm(related)
    if not related_norm or related_norm in current_norms or related_norm in _random_prompt_noise_tags():
        return False
    if related_norm in RANDOM_BAD_LOOKUP_TAGS or "kiss" in related_norm:
        return False
    if related_norm == "male_focus" and "1boy" not in current_norms:
        return False
    if related_norm == "female_focus" and not current_norms.intersection({"1girl", "2girls"}):
        return False
    if "no_humans" in current_norms:
        if related_norm in {"male_focus", "female_focus", "pov", "solo_focus"}:
            return False
        if related_norm.startswith(("holding_", "looking_", "hand_", "arm_", "leg_")):
            return False
    return True


def _subject_accepts_character(subject_id):
    return _prompt_lookup_norm(subject_id) in {"solo_girl", "solo_boy", "duo"}


def _character_subject_matches(row, subject_id):
    hint = _prompt_lookup_norm(row.get("subject_hint"))
    subject = _prompt_lookup_norm(subject_id)
    if not hint:
        return True
    if subject == "solo_boy":
        return hint == "1boy"
    if subject in {"solo_girl", "duo"}:
        return hint in {"1girl", "2girls", "multiple_girls"}
    return False


def _pick_random_character_tags(rng, subject_id):
    if not _subject_accepts_character(subject_id):
        return []
    rows = [row for row in _random_prompt_character_rows() if _character_subject_matches(row, subject_id)]
    if not rows:
        rows = _random_prompt_character_rows()
    if not rows:
        return []
    top = rows[: min(len(rows), RANDOM_CHARACTER_SAMPLE_POOL)]
    picked = rng.choice(top)
    tags = [picked.get("character_tag")]
    if picked.get("copyright_tag"):
        tags.append(picked.get("copyright_tag"))
    return [tag for tag in tags if tag]


def _dedupe_tags(tags):
    output = []
    seen = set()
    for tag in tags:
        clean = _safe_danbooru_tag(tag)
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(clean)
    return output


def _pick_group(rng, groups):
    if not groups:
        return []
    picked = rng.choice(groups)
    return list(picked or [])


def _pick_weighted_profile(rng, profiles):
    rows = [profile for profile in profiles or [] if isinstance(profile, dict)]
    if not rows:
        return {}
    weighted = []
    total = 0
    for profile in rows:
        weight = max(1, _safe_int(profile.get("weight"), 1))
        total += weight
        weighted.append((total, profile))
    target = rng.uniform(0, total)
    for upper, profile in weighted:
        if target <= upper:
            return profile
    return weighted[-1][1]


def _extend_tag_group(tags, slots, slot_name, values):
    clean_values = [item for item in values or [] if _clean_text(item)]
    if not clean_values:
        return
    tags.extend(clean_values)
    slots.append({"slot": slot_name, "values": clean_values})


def _random_prompt_lookup_terms(rng, subject, scene):
    terms = []
    for value in list(subject.get("lookup_terms") or []) + list(scene.get("lookup_terms") or []):
        clean = _clean_text(value)
        if clean and clean not in terms:
            terms.append(clean)
    rng.shuffle(terms)
    return terms[:3]


def _compose_developer_nsfw_random_prompt(preset_name="", scene_theme="", lang="cn", seed=None):
    rng = random.Random(seed) if seed is not None else random.Random()
    profile = _pick_weighted_profile(rng, RANDOM_PROMPT_NSFW_PROFILES)
    picked_slots = []
    prompt_tags = []

    _extend_tag_group(prompt_tags, picked_slots, "rating", ["nsfw", "rating_explicit", "adult"])
    _extend_tag_group(prompt_tags, picked_slots, "subject", profile.get("tags"))
    character_tags = _pick_adult_random_character_tags(
        rng,
        profile.get("subject_id"),
        chance=profile.get("character_chance", 1.0),
        copyright_chance=profile.get("copyright_chance", 1.0),
    )
    _extend_tag_group(prompt_tags, picked_slots, "character", character_tags)
    _extend_tag_group(prompt_tags, picked_slots, "setting", _pick_group(rng, profile.get("setting")))
    _extend_tag_group(prompt_tags, picked_slots, "pose", _pick_group(rng, profile.get("pose")))
    _extend_tag_group(prompt_tags, picked_slots, "adult_action", _pick_group(rng, profile.get("action")))
    _extend_tag_group(prompt_tags, picked_slots, "adult_expression", _pick_group(rng, profile.get("expression")))
    _extend_tag_group(prompt_tags, picked_slots, "adult_body_detail", _pick_group(rng, profile.get("body_detail")))
    _extend_tag_group(prompt_tags, picked_slots, "adult_finish_detail", _pick_group(rng, profile.get("finish_detail")))
    if rng.random() <= max(0.0, min(1.0, _safe_float(profile.get("lighting_chance"), 1.0))):
        _extend_tag_group(prompt_tags, picked_slots, "lighting", _pick_group(rng, profile.get("lighting")))

    association_tags = _random_prompt_adult_stats_tags(
        profile.get("trigger_tags"),
        prompt_tags,
        rng,
        max_count=max(0, _safe_int(profile.get("association_max"), 6)),
        allowed_slots=profile.get("association_slots"),
    )
    _extend_tag_group(prompt_tags, picked_slots, "adult_association_stats", association_tags)
    prompt = ", ".join(_dedupe_tags(prompt_tags))
    title = "Random Prompt (NSFW)" if _clean_lang(lang) == "en" else "随机提示词(NSFW)"
    return {
        "ok": True,
        "preset": _clean_text(preset_name),
        "scene_theme": _clean_text(scene_theme),
        "item": {
            "id": "developer_random_nsfw",
            "target": "positive_prompt",
            "mode": "replace",
            "title": title,
            "prompt": prompt,
            "seed_terms": [_safe_danbooru_tag(tag) for tag in profile.get("trigger_tags") or []],
            "slots": picked_slots,
            "recipe": {
                "mode": "developer_nsfw",
                "profile": profile.get("id"),
                "character": character_tags[:1],
                "stat_triggers": [_safe_danbooru_tag(tag) for tag in profile.get("trigger_tags") or []],
            },
            "source": "developer_nsfw_random_prompt",
        },
    }


def compose_random_prompt(preset_name="", scene_theme="", lang="cn", seed=None, source_mode="all", prompt_text=""):
    if _developer_random_prompt_nsfw_enabled() or _random_prompt_nsfw_requested(prompt_text):
        return _compose_developer_nsfw_random_prompt(
            preset_name=preset_name,
            scene_theme=scene_theme,
            lang=lang,
            seed=seed,
        )

    rng = random.Random(seed) if seed is not None else random.Random()
    subject = rng.choice(RANDOM_SUBJECT_PROFILES)
    scene = rng.choice(RANDOM_SCENE_PROFILES)
    scenery_only = "no_humans" in subject.get("tags", [])
    composition_key = "scenery" if scenery_only else "character"
    picked_slots = []
    lookup_terms = []
    prompt_tags = []

    _extend_tag_group(prompt_tags, picked_slots, "subject", subject.get("tags"))
    character_tags = _pick_random_character_tags(rng, subject.get("id"))
    _extend_tag_group(prompt_tags, picked_slots, "character", character_tags)
    _extend_tag_group(prompt_tags, picked_slots, "appearance", _pick_group(rng, subject.get("appearance")))
    _extend_tag_group(prompt_tags, picked_slots, "outfit", _pick_group(rng, subject.get("outfit")))
    _extend_tag_group(prompt_tags, picked_slots, "action", _pick_group(rng, subject.get("action")))
    _extend_tag_group(prompt_tags, picked_slots, "setting", scene.get("tags"))
    _extend_tag_group(prompt_tags, picked_slots, "scene_detail", _pick_group(rng, scene.get("details")))
    _extend_tag_group(prompt_tags, picked_slots, "lighting", _pick_group(rng, scene.get("lighting")))
    _extend_tag_group(prompt_tags, picked_slots, "composition", _pick_group(rng, RANDOM_COMPOSITION_GROUPS.get(composition_key)))
    _extend_tag_group(prompt_tags, picked_slots, "atmosphere", _pick_group(rng, RANDOM_ATMOSPHERE_GROUPS))
    _extend_tag_group(prompt_tags, picked_slots, "style", _pick_group(rng, RANDOM_STYLE_GROUPS))

    for term in _random_prompt_lookup_terms(rng, subject, scene):
        tags = _lookup_prompt_tags(term, source_mode=source_mode, rng=rng, max_count=1)
        if tags:
            lookup_terms.append(term)
            _extend_tag_group(prompt_tags, picked_slots, "danbooru_related", tags)

    association_tags = _random_prompt_association_tags(prompt_tags, rng, max_count=5)
    _extend_tag_group(prompt_tags, picked_slots, "association_stats", association_tags)

    prompt_tags.extend(RANDOM_QUALITY_TAGS)

    prompt = ", ".join(_dedupe_tags(prompt_tags))
    return {
        "ok": True,
        "preset": _clean_text(preset_name),
        "scene_theme": _clean_text(scene_theme),
        "item": {
            "id": "local_random_danbooru",
            "target": "positive_prompt",
            "mode": "replace",
            "title": "Random Prompt" if _clean_lang(lang) == "en" else "随机提示词",
            "prompt": prompt,
            "seed_terms": lookup_terms,
            "slots": picked_slots,
            "recipe": {
                "subject": subject.get("id"),
                "scene": scene.get("id"),
                "character": character_tags[:1],
            },
            "source": "local_prompt_recipe_danbooru_lookup",
        },
    }
