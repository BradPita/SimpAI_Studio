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
]

RANDOM_STYLE_GROUPS = [
    ["anime_style", "clean_lineart"],
    ["cinematic_lighting", "depth_of_field"],
    ["painterly", "soft_shading"],
    ["vibrant_colors", "sharp_focus"],
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
    {
        "id": "festival_night",
        "tags": ["festival", "night", "lantern", "crowd", "food_stall"],
        "details": [
            ["fireworks", "paper_lantern", "yakisoba"],
            ["mask_stall", "goldfish_scooping", "banner"],
            ["torii", "stone_steps", "hanging_lantern"],
            ["cotton_candy", "wooden_booth", "crowd_blur"],
        ],
        "lighting": [
            ["warm_lantern_light", "night_sky", "rim_lighting"],
            ["fireworks", "colorful_light", "backlighting"],
            ["soft_shadow", "glowing_sign", "blue_hour"],
        ],
        "lookup_terms": ["festival", "lantern", "fireworks", "food stall"],
    },
    {
        "id": "train_station_morning",
        "tags": ["train_station", "platform", "morning", "commute"],
        "details": [
            ["train", "ticket_gate", "signboard"],
            ["bench", "vending_machine", "timetable"],
            ["suitcase", "overpass", "sunbeam"],
            ["railway_tracks", "distant_train", "motion_blur"],
        ],
        "lighting": [
            ["morning_light", "soft_shadow", "clear_sky"],
            ["overcast", "diffused_light", "muted_colors"],
            ["backlighting", "light_rays", "warm_light"],
        ],
        "lookup_terms": ["train station", "platform", "suitcase", "commute"],
    },
    {
        "id": "stage_performance",
        "tags": ["stage", "spotlight", "audience", "concert"],
        "details": [
            ["microphone", "speaker", "confetti"],
            ["stage_lights", "smoke_machine", "glowstick"],
            ["curtains", "music_note", "backdrop"],
            ["dance_floor", "sparkles", "crowd_blur"],
        ],
        "lighting": [
            ["spotlight", "colorful_light", "high_contrast"],
            ["rim_lighting", "stage_lights", "dark_background"],
            ["glitter", "backlighting", "sharp_focus"],
        ],
        "lookup_terms": ["stage", "microphone", "concert", "spotlight"],
    },
    {
        "id": "sci_fi_workshop",
        "tags": ["laboratory", "workshop", "hologram", "monitor", "machinery"],
        "details": [
            ["control_panel", "floating_screen", "cable"],
            ["robot_arm", "toolbox", "blue_glow"],
            ["mechanical_parts", "schematic", "workbench"],
            ["glass_wall", "server_rack", "warning_light"],
        ],
        "lighting": [
            ["blue_light", "rim_lighting", "screen_glow"],
            ["neon_light", "low_light", "high_contrast"],
            ["cool_light", "sharp_focus", "reflected_light"],
        ],
        "lookup_terms": ["hologram", "workshop", "machinery", "control panel"],
    },
    {
        "id": "sports_court",
        "tags": ["sports", "court", "outdoors", "blue_sky"],
        "details": [
            ["basketball", "chain_link_fence", "water_bottle"],
            ["running_track", "finish_line", "sports_bag"],
            ["tennis_court", "racket", "net"],
            ["soccer_field", "goal", "grass"],
        ],
        "lighting": [
            ["sunny", "clear_sky", "sharp_shadow"],
            ["golden_hour", "warm_light", "motion_blur"],
            ["overcast", "diffused_light", "fresh_air"],
        ],
        "lookup_terms": ["sports", "basketball", "running", "court"],
    },
    {
        "id": "art_studio",
        "tags": ["art_studio", "easel", "canvas", "paint"],
        "details": [
            ["paintbrush", "palette", "apron"],
            ["sketchbook", "pencil", "paper"],
            ["clay_model", "shelf", "tool"],
            ["window", "sunbeam", "paint_splatter"],
        ],
        "lighting": [
            ["north_light", "soft_shadow", "warm_light"],
            ["afternoon_light", "dust_particles", "calm"],
            ["lamplight", "cozy", "shallow_depth_of_field"],
        ],
        "lookup_terms": ["art studio", "paintbrush", "easel", "sketchbook"],
    },
]


def _sfw_scene_profile(scene_id, tags, details, lighting, lookup_terms):
    return {
        "id": scene_id,
        "tags": tags,
        "details": details,
        "lighting": lighting,
        "lookup_terms": lookup_terms,
    }


RANDOM_SCENE_PROFILES.extend([
    _sfw_scene_profile(
        "airport_terminal",
        ["airport", "terminal", "glass_wall", "luggage"],
        [["departure_board", "suitcase", "ticket"], ["security_gate", "queue", "signboard"], ["large_window", "airplane", "runway"]],
        [["morning_light", "glass_reflection", "clear_sky"], ["overcast", "diffused_light", "muted_colors"], ["night", "soft_light", "window_reflection"]],
        ["airport terminal", "luggage", "departure board"],
    ),
    _sfw_scene_profile(
        "subway_platform",
        ["subway", "platform", "train", "underground"],
        [["yellow_line", "tile_wall", "map"], ["turnstile", "ticket_gate", "crowd"], ["motion_blur", "arriving_train", "signboard"]],
        [["fluorescent_light", "cool_light", "reflection"], ["dim_light", "high_contrast", "long_shadow"], ["neon_light", "depth_of_field", "blue_light"]],
        ["subway platform", "train", "ticket gate"],
    ),
    _sfw_scene_profile(
        "shopping_arcade",
        ["shopping_arcade", "storefront", "crowd", "signboard"],
        [["glass_roof", "shop_window", "mannequin"], ["escalator", "poster", "bag"], ["food_court", "table", "menu"]],
        [["soft_indoor_light", "reflected_light", "clean"], ["evening", "warm_light", "glowing_sign"], ["skylight", "bright", "sharp_focus"]],
        ["shopping arcade", "storefront", "escalator"],
    ),
    _sfw_scene_profile(
        "old_town_alley",
        ["old_town", "alley", "cobblestone", "building"],
        [["flower_pot", "wooden_door", "window"], ["street_lamp", "bicycle", "stone_wall"], ["stairs", "awning", "shopfront"]],
        [["golden_hour", "warm_light", "soft_shadow"], ["rain", "wet_ground", "reflection"], ["morning", "sunbeam", "calm"]],
        ["old town alley", "cobblestone", "street lamp"],
    ),
    _sfw_scene_profile(
        "rooftop_garden",
        ["rooftop", "garden", "cityscape", "plants"],
        [["railing", "flower_pot", "bench"], ["greenhouse", "water_tank", "stairs"], ["table", "parasol", "skyline"]],
        [["sunset", "backlighting", "orange_sky"], ["blue_hour", "city_lights", "rim_lighting"], ["clear_sky", "soft_light", "wind"]],
        ["rooftop garden", "cityscape", "plants"],
    ),
    _sfw_scene_profile(
        "museum_gallery",
        ["museum", "gallery", "painting", "marble_floor"],
        [["frame", "bench", "spotlight"], ["sculpture", "pedestal", "rope_barrier"], ["large_hall", "skylight", "quiet"]],
        [["gallery_light", "soft_shadow", "clean"], ["spotlight", "dark_background", "high_contrast"], ["skylight", "diffused_light", "calm"]],
        ["museum gallery", "painting", "sculpture"],
    ),
    _sfw_scene_profile(
        "classroom_afternoon",
        ["classroom", "desk", "chalkboard", "window"],
        [["school_desk", "notebook", "pencil"], ["curtains", "sunbeam", "chair"], ["bulletin_board", "clock", "book_stack"]],
        [["afternoon_light", "warm_light", "dust_particles"], ["overcast", "diffused_light", "quiet"], ["sunset", "orange_light", "long_shadow"]],
        ["classroom", "school desk", "chalkboard"],
    ),
    _sfw_scene_profile(
        "kitchen_table",
        ["kitchen", "table", "food", "window"],
        [["cutting_board", "vegetables", "knife"], ["steam", "soup", "bowl"], ["apron", "sink", "tile_wall"]],
        [["morning_light", "soft_shadow", "warm_light"], ["lamplight", "cozy", "shallow_depth_of_field"], ["sunbeam", "clean", "bright"]],
        ["kitchen table", "food", "apron"],
    ),
    _sfw_scene_profile(
        "greenhouse",
        ["greenhouse", "plants", "glass_roof", "flowers"],
        [["watering_can", "terracotta_pot", "vines"], ["orchid", "fern", "mist"], ["wooden_table", "seedling", "garden_tool"]],
        [["sunbeam", "diffused_light", "warm_light"], ["mist", "soft_focus", "fresh"], ["rain", "window_reflection", "calm"]],
        ["greenhouse", "plants", "watering can"],
    ),
    _sfw_scene_profile(
        "aquarium_tunnel",
        ["aquarium", "underwater", "fish", "glass_tunnel"],
        [["shark", "coral", "blue_light"], ["jellyfish", "reflection", "visitor"], ["bubble", "water", "school_of_fish"]],
        [["blue_light", "caustics", "soft_shadow"], ["glowing_jellyfish", "dark_background", "rim_lighting"], ["reflected_light", "dreamy", "depth_of_field"]],
        ["aquarium", "jellyfish", "underwater"],
    ),
    _sfw_scene_profile(
        "bamboo_forest",
        ["bamboo_forest", "path", "greenery", "sunlight"],
        [["bamboo", "stone_path", "fallen_leaves"], ["torii", "moss", "mist"], ["stream", "bridge", "fern"]],
        [["morning", "dappled_sunlight", "soft_shadow"], ["fog", "diffused_light", "calm"], ["golden_hour", "warm_light", "wind"]],
        ["bamboo forest", "stone path", "mist"],
    ),
    _sfw_scene_profile(
        "snowy_mountain",
        ["mountain", "snow", "pine_tree", "clouds"],
        [["mountain_peak", "snowfield", "footprints"], ["cabin", "smoke", "frozen_lake"], ["cliff", "distant_mountains", "wind"]],
        [["clear_sky", "bright_light", "sharp_shadow"], ["snowfall", "diffused_light", "soft_focus"], ["sunset", "pink_sky", "backlighting"]],
        ["snowy mountain", "snow", "cabin"],
    ),
    _sfw_scene_profile(
        "desert_oasis",
        ["desert", "oasis", "sand", "palm_tree"],
        [["water", "date_palm", "tent"], ["camel", "dune", "carpet"], ["ruins", "sun", "heat_haze"]],
        [["sunset", "orange_sky", "long_shadow"], ["noon", "harsh_light", "clear_sky"], ["moonlight", "cool_light", "stars"]],
        ["desert oasis", "sand dune", "palm tree"],
    ),
    _sfw_scene_profile(
        "coral_reef",
        ["coral_reef", "underwater", "fish", "sunlight"],
        [["coral", "sea_turtle", "bubble"], ["reef", "tropical_fish", "seaweed"], ["sunbeam", "clear_water", "shell"]],
        [["caustics", "blue_light", "sparkling_water"], ["sunlight", "soft_shadow", "clear"], ["deep_blue", "glowing", "dreamy"]],
        ["coral reef", "sea turtle", "underwater"],
    ),
    _sfw_scene_profile(
        "volcanic_landscape",
        ["volcano", "lava", "rock", "smoke"],
        [["lava_flow", "ash", "cracked_ground"], ["obsidian", "steam", "red_glow"], ["cliff", "embers", "dark_clouds"]],
        [["red_light", "high_contrast", "rim_lighting"], ["smoke", "low_light", "dramatic"], ["sunset", "orange_sky", "backlighting"]],
        ["volcanic landscape", "lava", "ash"],
    ),
    _sfw_scene_profile(
        "waterfall_gorge",
        ["waterfall", "gorge", "river", "rocks"],
        [["mist", "rainbow", "moss"], ["wooden_bridge", "cliff", "fern"], ["pool", "wet_rocks", "spray"]],
        [["sunbeam", "mist", "soft_light"], ["overcast", "diffused_light", "calm"], ["golden_hour", "warm_light", "sparkling_water"]],
        ["waterfall", "gorge", "mist"],
    ),
    _sfw_scene_profile(
        "autumn_park",
        ["park", "autumn", "fallen_leaves", "bench"],
        [["maple_leaf", "path", "street_lamp"], ["pond", "duck", "wooden_bridge"], ["bicycle", "scarf", "picnic"]],
        [["golden_hour", "warm_light", "soft_shadow"], ["overcast", "muted_colors", "calm"], ["sunbeam", "falling_leaves", "gentle_wind"]],
        ["autumn park", "fallen leaves", "bench"],
    ),
    _sfw_scene_profile(
        "space_station",
        ["space_station", "space", "window", "earth"],
        [["airlock", "spacesuit", "control_panel"], ["solar_panel", "hatch", "floating"], ["observation_deck", "planet", "stars"]],
        [["screen_glow", "blue_light", "rim_lighting"], ["earthlight", "dark_background", "soft_shadow"], ["warning_light", "high_contrast", "low_light"]],
        ["space station", "spacesuit", "control panel"],
    ),
    _sfw_scene_profile(
        "starship_bridge",
        ["starship", "bridge", "control_panel", "space"],
        [["captain_chair", "hologram", "monitor"], ["window", "stars", "planet"], ["console", "crew", "warning_light"]],
        [["screen_glow", "blue_light", "sharp_focus"], ["red_alert", "high_contrast", "rim_lighting"], ["starlight", "dark_background", "cool_light"]],
        ["starship bridge", "hologram", "monitor"],
    ),
    _sfw_scene_profile(
        "lunar_base",
        ["moon", "lunar_base", "space", "crater"],
        [["dome", "rover", "antenna"], ["airlock", "spacesuit", "footprints"], ["earth", "solar_panel", "rock"]],
        [["earthlight", "cool_light", "dark_sky"], ["sunrise", "long_shadow", "sharp_light"], ["blue_light", "rim_lighting", "clear"]],
        ["lunar base", "moon", "rover"],
    ),
    _sfw_scene_profile(
        "alien_market",
        ["alien_market", "market", "neon_lights", "crowd"],
        [["alien_vendor", "floating_sign", "stall"], ["crystal", "strange_fruit", "lantern"], ["hover_vehicle", "street", "glowing"]],
        [["neon_light", "colorful_light", "reflected_light"], ["night", "rim_lighting", "mist"], ["screen_glow", "blue_light", "depth_of_field"]],
        ["alien market", "neon lights", "crystal"],
    ),
    _sfw_scene_profile(
        "robot_factory",
        ["factory", "robot", "assembly_line", "machinery"],
        [["robot_arm", "conveyor_belt", "sparks"], ["toolbox", "cable", "warning_sign"], ["metal_floor", "steam", "monitor"]],
        [["industrial_light", "high_contrast", "sharp_focus"], ["orange_light", "sparks", "rim_lighting"], ["cool_light", "screen_glow", "metal_reflection"]],
        ["robot factory", "assembly line", "machinery"],
    ),
    _sfw_scene_profile(
        "alien_biodome",
        ["alien_biodome", "glass_dome", "plants", "glowing"],
        [["alien_flower", "pool", "mist"], ["floating_seed", "vines", "crystal"], ["research_station", "path", "blue_glow"]],
        [["bioluminescence", "soft_light", "dreamy"], ["blue_light", "rim_lighting", "mist"], ["sunbeam", "glass_reflection", "calm"]],
        ["alien biodome", "glowing plants", "crystal"],
    ),
    _sfw_scene_profile(
        "arcane_library",
        ["arcane_library", "bookshelf", "magic_circle", "candle"],
        [["floating_book", "rune", "ladder"], ["spellbook", "crystal_ball", "desk"], ["stained_glass", "dust_particles", "old_books"]],
        [["candlelight", "warm_light", "soft_shadow"], ["blue_glow", "magic_circle", "rim_lighting"], ["moonlight", "window", "mysterious_light"]],
        ["arcane library", "floating book", "magic circle"],
    ),
    _sfw_scene_profile(
        "floating_island",
        ["floating_island", "sky", "clouds", "waterfall"],
        [["ancient_tree", "bridge", "wind"], ["ruins", "crystal", "grass"], ["airship", "distant_islands", "sunlight"]],
        [["sunlight", "god_rays", "clear_sky"], ["sunset", "orange_sky", "backlighting"], ["moonlight", "clouds", "soft_shadow"]],
        ["floating island", "sky", "waterfall"],
    ),
    _sfw_scene_profile(
        "dragon_cave",
        ["cave", "dragon", "treasure", "crystal"],
        [["gold", "gem", "rock"], ["stalactite", "torch", "smoke"], ["ancient_bone", "water", "glow"]],
        [["torchlight", "warm_light", "dark_background"], ["crystal_glow", "blue_light", "rim_lighting"], ["red_light", "smoke", "dramatic"]],
        ["dragon cave", "treasure", "crystal"],
    ),
    _sfw_scene_profile(
        "sky_castle",
        ["castle", "sky", "clouds", "fantasy"],
        [["tower", "flag", "bridge"], ["balcony", "stained_glass", "garden"], ["airship", "waterfall", "distant_mountains"]],
        [["sunrise", "golden_light", "clouds"], ["moonlight", "blue_light", "soft_shadow"], ["sunset", "backlighting", "orange_sky"]],
        ["sky castle", "tower", "clouds"],
    ),
    _sfw_scene_profile(
        "enchanted_garden",
        ["enchanted_garden", "flowers", "glowing", "butterfly"],
        [["mushroom", "fairy_light", "pond"], ["rose_arch", "fountain", "vines"], ["firefly", "grass", "sparkles"]],
        [["soft_light", "glowing", "dreamy"], ["moonlight", "firefly", "blue_light"], ["morning", "dew", "sunbeam"]],
        ["enchanted garden", "glowing flowers", "butterfly"],
    ),
    _sfw_scene_profile(
        "crystal_cavern",
        ["crystal_cavern", "cave", "glowing", "water"],
        [["crystal", "underground_lake", "reflection"], ["stone_bridge", "stalactite", "mist"], ["geode", "blue_glow", "rock"]],
        [["crystal_glow", "blue_light", "reflected_light"], ["low_light", "rim_lighting", "dark_background"], ["soft_light", "mist", "dreamy"]],
        ["crystal cavern", "underground lake", "blue glow"],
    ),
    _sfw_scene_profile(
        "dungeon_corridor",
        ["dungeon", "corridor", "stone_wall", "torch"],
        [["wooden_door", "chain", "barrel"], ["stairs", "shadow", "moss"], ["gate", "cobweb", "water"]],
        [["torchlight", "warm_light", "long_shadow"], ["low_light", "dark_background", "high_contrast"], ["blue_light", "mist", "mysterious"]],
        ["dungeon corridor", "torch", "stone wall"],
    ),
    _sfw_scene_profile(
        "treasure_room",
        ["treasure_room", "gold", "chest", "gem"],
        [["treasure_chest", "coins", "jewel"], ["statue", "pillar", "torch"], ["map", "scroll", "key"]],
        [["golden_light", "sparkles", "warm_light"], ["torchlight", "soft_shadow", "dark_background"], ["sunbeam", "dust_particles", "mysterious"]],
        ["treasure room", "gold", "chest"],
    ),
    _sfw_scene_profile(
        "airship_deck",
        ["airship", "deck", "sky", "clouds"],
        [["sail", "rope", "wooden_floor"], ["propeller", "railing", "wind"], ["map_table", "compass", "distant_mountains"]],
        [["sunset", "backlighting", "orange_sky"], ["clear_sky", "bright_light", "wind"], ["storm_clouds", "dramatic", "high_contrast"]],
        ["airship deck", "clouds", "compass"],
    ),
    _sfw_scene_profile(
        "boss_arena",
        ["arena", "ruins", "dramatic", "wide_shot"],
        [["broken_pillar", "magic_circle", "cracked_floor"], ["torch", "banner", "stone_gate"], ["dust", "weapon", "storm_clouds"]],
        [["dramatic_lighting", "high_contrast", "rim_lighting"], ["red_light", "smoke", "dark_background"], ["moonlight", "fog", "blue_light"]],
        ["boss arena", "ruins", "magic circle"],
    ),
    _sfw_scene_profile(
        "parade_street",
        ["parade", "street", "crowd", "confetti"],
        [["float", "banner", "balloon"], ["marching_band", "drum", "flag"], ["food_stall", "streamer", "smile"]],
        [["sunny", "colorful_light", "sharp_focus"], ["golden_hour", "warm_light", "crowd_blur"], ["night", "lantern", "glowing_sign"]],
        ["parade", "confetti", "balloon"],
    ),
    _sfw_scene_profile(
        "wedding_garden",
        ["wedding", "garden", "flowers", "arch"],
        [["flower_arch", "chair", "ribbon"], ["cake", "table", "bouquet"], ["fountain", "path", "white_cloth"]],
        [["soft_light", "warm_light", "bloom"], ["sunset", "golden_light", "backlighting"], ["overcast", "diffused_light", "calm"]],
        ["wedding garden", "bouquet", "flower arch"],
    ),
    _sfw_scene_profile(
        "market_bazaar",
        ["market", "bazaar", "stall", "crowd"],
        [["spice", "basket", "cloth"], ["fruit", "awning", "signboard"], ["lantern", "carpet", "ceramic"]],
        [["warm_light", "sunbeam", "colorful"], ["evening", "lantern", "soft_shadow"], ["overcast", "diffused_light", "busy"]],
        ["market bazaar", "spice", "fruit stall"],
    ),
    _sfw_scene_profile(
        "tea_house",
        ["tea_house", "tatami", "teacup", "window"],
        [["tea_set", "low_table", "flowers"], ["shoji", "garden", "sunbeam"], ["kettle", "steam", "wooden_floor"]],
        [["warm_light", "soft_shadow", "calm"], ["morning", "diffused_light", "peaceful"], ["rainy_day", "window_light", "muted_colors"]],
        ["tea house", "teacup", "tatami"],
    ),
])

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

RANDOM_SFW_THEME_PROFILES = [
    {
        "id": "cafe_daily_work",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["quiet_library", "cozy_room", "art_studio", "train_station_morning"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop"],
        "tags": ["slice_of_life"],
        "outfit": [["apron", "rolled_up_sleeves"], ["cardigan", "casual"], ["shirt", "vest"]],
        "action": [["serving_food", "holding_tray"], ["pouring_coffee", "gentle_smile"], ["writing", "looking_down"]],
        "interaction": [["talking", "smile"], ["looking_at_another", "laughing"], ["handing_object", "soft_smile"]],
        "prop": [["coffee_cup", "dessert", "menu"], ["teapot", "book", "flower_vase"], ["notebook", "pen", "receipt"]],
        "scene_detail": [["counter", "steam", "chalkboard_menu"], ["wooden_table", "chair", "warm_light"]],
        "lookup_terms": ["coffee cup", "serving food", "slice of life"],
    },
    {
        "id": "festival_outing",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["festival_night", "seaside_evening", "rainy_neon_street"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene"],
        "tags": ["festival"],
        "outfit": [["yukata", "hair_ornament"], ["casual", "hoodie"], ["kimono", "wide_sleeves"]],
        "action": [["holding_mask", "looking_at_viewer"], ["buying_food", "smile"], ["watching_fireworks", "looking_up"]],
        "interaction": [["holding_hands", "laughing"], ["sharing_food", "smile"], ["walking_together", "crowd"]],
        "prop": [["paper_lantern", "fox_mask", "food_stall"], ["cotton_candy", "balloon", "festival_fan"]],
        "scene_detail": [["fireworks", "lantern", "night_sky"], ["stall", "banner", "crowd_blur"]],
        "lookup_terms": ["festival", "yukata", "fireworks"],
    },
    {
        "id": "fantasy_quest",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["fantasy_ruins", "sunlit_forest_path"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene"],
        "tags": ["fantasy", "adventure"],
        "outfit": [["cloak", "boots", "belt"], ["armor", "cape"], ["traveling_clothes", "gloves"]],
        "action": [["holding_map", "looking_forward"], ["casting_spell", "dynamic_pose"], ["reaching_out", "serious"]],
        "interaction": [["pointing", "looking_at_another"], ["protective_stance", "determined"], ["team_pose", "smile"]],
        "prop": [["map", "compass", "satchel"], ["staff", "magic_circle", "glowing_orb"], ["sword", "scabbard", "pouch"]],
        "scene_detail": [["ancient_gate", "rune", "floating_particles"], ["campfire", "moss", "broken_pillar"]],
        "lookup_terms": ["fantasy", "map", "magic circle"],
    },
    {
        "id": "sci_fi_operator",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["sci_fi_workshop", "rainy_neon_street"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "style_light"],
        "tags": ["science_fiction"],
        "outfit": [["bodysuit", "jacket", "gloves"], ["pilot_suit", "headset"], ["lab_coat", "goggles"]],
        "action": [["operating_console", "focused"], ["repairing_machine", "kneeling"], ["pointing_at_screen", "serious"]],
        "interaction": [["discussing_plan", "looking_at_another"], ["passing_tool", "focused"], ["team_pose", "monitor"]],
        "prop": [["hologram", "control_panel", "cable"], ["tablet_pc", "toolbox", "robot_arm"], ["blueprint", "mechanical_parts"]],
        "scene_detail": [["screen_glow", "server_rack", "warning_light"], ["workbench", "sparks", "blue_glow"]],
        "lookup_terms": ["hologram", "control panel", "pilot suit"],
    },
    {
        "id": "idol_stage_show",
        "weight": 3,
        "subject_ids": ["solo_girl", "duo"],
        "scene_ids": ["stage_performance", "festival_night"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "style_light"],
        "tags": ["idol", "performance"],
        "outfit": [["idol_clothes", "frills", "hair_ribbon"], ["stage_outfit", "boots"], ["dress", "detached_sleeves"]],
        "action": [["singing", "holding_microphone"], ["dancing", "dynamic_pose"], ["waving", "big_smile"]],
        "interaction": [["duet", "looking_at_another"], ["group_pose", "smile"], ["reaching_out", "audience"]],
        "prop": [["microphone", "glowstick", "confetti"], ["speaker", "stage_light", "music_note"]],
        "scene_detail": [["spotlight", "stage", "audience"], ["curtains", "sparkles", "crowd_blur"]],
        "lookup_terms": ["idol", "microphone", "stage"],
    },
    {
        "id": "sports_training",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["sports_court", "sunlit_forest_path", "seaside_evening"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop"],
        "tags": ["sports"],
        "outfit": [["sportswear", "sneakers"], ["track_jacket", "shorts"], ["jersey", "knee_socks"]],
        "action": [["running", "dynamic_pose"], ["jumping", "determined"], ["stretching", "smile"]],
        "interaction": [["passing_ball", "looking_at_another"], ["high_five", "laughing"], ["team_pose", "energetic"]],
        "prop": [["basketball", "water_bottle", "towel"], ["racket", "sports_bag"], ["soccer_ball", "goal"]],
        "scene_detail": [["court_line", "fence", "blue_sky"], ["running_track", "finish_line", "motion_blur"]],
        "lookup_terms": ["sportswear", "basketball", "running"],
    },
    {
        "id": "travel_snapshot",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["train_station_morning", "seaside_evening", "rainy_neon_street", "festival_night"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene"],
        "tags": ["travel"],
        "outfit": [["backpack", "jacket"], ["coat", "scarf"], ["casual", "sneakers"]],
        "action": [["taking_photo", "camera"], ["checking_map", "looking_down"], ["waving", "smile"]],
        "interaction": [["showing_photo", "laughing"], ["walking_together", "suitcase"], ["pointing", "looking_away"]],
        "prop": [["camera", "suitcase", "map"], ["ticket", "phone", "backpack"], ["umbrella", "travel_bag"]],
        "scene_detail": [["signboard", "platform", "sunbeam"], ["street_corner", "shopfront", "reflection"]],
        "lookup_terms": ["camera", "suitcase", "travel"],
    },
    {
        "id": "art_studio_session",
        "weight": 2,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["art_studio", "quiet_library", "cozy_room"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene"],
        "tags": ["art"],
        "outfit": [["apron", "rolled_up_sleeves"], ["cardigan", "casual"], ["shirt", "gloves"]],
        "action": [["painting", "holding_brush"], ["sketching", "looking_down"], ["mixing_paint", "focused"]],
        "interaction": [["showing_sketch", "smile"], ["teaching", "pointing"], ["looking_at_canvas", "thoughtful"]],
        "prop": [["paintbrush", "palette", "canvas"], ["sketchbook", "pencil", "easel"], ["paint_tube", "rag", "jar"]],
        "scene_detail": [["paint_splatter", "wooden_floor", "sunbeam"], ["shelf", "clay_model", "paper"]],
        "lookup_terms": ["paintbrush", "easel", "sketchbook"],
    },
    {
        "id": "animal_companion",
        "weight": 2,
        "subject_ids": ["solo_girl", "solo_boy", "duo", "animal_focus"],
        "scene_ids": ["sunlit_forest_path", "cozy_room", "seaside_evening", "festival_night"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "prop", "scene"],
        "tags": ["animal", "pet"],
        "outfit": [["casual", "sneakers"], ["coat", "scarf"], ["apron"]],
        "action": [["feeding_animal", "gentle_smile"], ["holding_pet", "smile"], ["playing", "laughing"]],
        "interaction": [["petting_animal", "looking_down"], ["walking_dog", "leash"], ["sharing_food", "smile"]],
        "prop": [["leash", "pet_bowl", "toy"], ["basket", "blanket", "ribbon"], ["treat", "small_bag"]],
        "scene_detail": [["grass", "flowers", "sunlight"], ["sofa", "blanket", "window_light"]],
        "lookup_terms": ["petting animal", "cat", "dog"],
    },
    {
        "id": "landscape_weather",
        "weight": 2,
        "subject_ids": ["scenery", "animal_focus"],
        "scene_ids": ["sunlit_forest_path", "seaside_evening", "rainy_neon_street", "fantasy_ruins"],
        "association_max": 4,
        "association_slots": ["scene", "prop", "style_light", "camera"],
        "tags": ["environment"],
        "outfit": [[]],
        "action": [["wind", "falling_leaves"], ["rain", "ripples"], ["sunlight", "floating_particles"]],
        "interaction": [[]],
        "prop": [["bird", "butterfly", "flower"], ["boat", "rope", "lantern"], ["umbrella", "puddle", "reflection"]],
        "scene_detail": [["distant_mountains", "clouds", "river"], ["waves", "seafoam", "sparkling_water"]],
        "lookup_terms": ["scenery", "rain", "sunlight"],
    },
    {
        "id": "still_life_corner",
        "weight": 2,
        "subject_ids": ["scenery", "animal_focus"],
        "scene_ids": ["quiet_library", "cozy_room", "art_studio"],
        "association_max": 4,
        "association_slots": ["scene", "prop", "style_light", "camera"],
        "tags": ["still_life"],
        "outfit": [[]],
        "action": [["sunbeam", "dust_particles"], ["steam", "soft_shadow"], ["falling_petals", "calm"]],
        "interaction": [[]],
        "prop": [["book", "coffee_cup", "flower_vase"], ["paintbrush", "palette", "sketchbook"], ["blanket", "plant", "chair"]],
        "scene_detail": [["wooden_table", "window", "warm_light"], ["shelf", "paper", "small_lamp"]],
        "lookup_terms": ["still life", "coffee cup", "flower vase"],
    },
    {
        "id": "urban_architecture",
        "weight": 2,
        "subject_ids": ["scenery", "animal_focus"],
        "scene_ids": ["rainy_neon_street", "train_station_morning", "sci_fi_workshop", "festival_night"],
        "association_max": 4,
        "association_slots": ["scene", "prop", "style_light", "camera"],
        "tags": ["architecture"],
        "outfit": [[]],
        "action": [["rain", "reflection"], ["moving_train", "motion_blur"], ["crowd_blur", "glowing_sign"]],
        "interaction": [[]],
        "prop": [["signboard", "street_lamp", "umbrella"], ["ticket_gate", "bench", "vending_machine"], ["lantern", "banner", "stairs"]],
        "scene_detail": [["vanishing_point", "leading_lines", "wet_ground"], ["platform", "overpass", "cityscape"]],
        "lookup_terms": ["architecture", "street lamp", "train station"],
    },
]

RANDOM_SFW_THEME_PROFILES.extend([
    {
        "id": "commuter_public_space",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["airport_terminal", "subway_platform", "shopping_arcade", "old_town_alley", "rooftop_garden"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene"],
        "tags": ["daily_life"],
        "outfit": [["coat", "scarf"], ["jacket", "backpack"], ["casual", "sneakers"]],
        "action": [["checking_phone", "looking_down"], ["waiting", "looking_away"], ["walking", "holding_bag"]],
        "interaction": [["asking_directions", "smile"], ["walking_together", "talking"], ["pointing", "looking_at_another"]],
        "prop": [["phone", "ticket", "bag"], ["suitcase", "coffee_cup", "map"], ["umbrella", "shopping_bag", "signboard"]],
        "scene_detail": [["crowd_blur", "signboard", "reflection"], ["glass_wall", "bench", "large_window"]],
        "lookup_terms": ["commute", "ticket", "shopping bag"],
    },
    {
        "id": "market_food_walk",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["market_bazaar", "kitchen_table", "tea_house", "shopping_arcade", "festival_night"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene"],
        "tags": ["food", "market"],
        "outfit": [["apron", "rolled_up_sleeves"], ["casual", "cardigan"], ["kimono", "hair_ornament"]],
        "action": [["tasting_food", "smile"], ["cooking", "focused"], ["holding_cup", "gentle_smile"]],
        "interaction": [["sharing_food", "laughing"], ["handing_object", "soft_smile"], ["talking", "looking_at_another"]],
        "prop": [["bowl", "chopsticks", "steam"], ["basket", "fruit", "spice"], ["teacup", "kettle", "dessert"]],
        "scene_detail": [["stall", "wooden_table", "menu"], ["steam", "warm_light", "flower_vase"]],
        "lookup_terms": ["food stall", "teacup", "cooking"],
    },
    {
        "id": "school_museum_visit",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["classroom_afternoon", "museum_gallery", "quiet_library", "arcane_library"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene"],
        "tags": ["study", "education"],
        "outfit": [["school_uniform", "pleated_skirt"], ["shirt", "necktie"], ["cardigan", "loafers"]],
        "action": [["reading", "looking_down"], ["taking_notes", "focused"], ["looking_at_painting", "thoughtful"]],
        "interaction": [["discussing", "looking_at_another"], ["showing_book", "smile"], ["pointing", "curious"]],
        "prop": [["notebook", "pencil", "book"], ["guidebook", "frame", "bench"], ["tablet_pc", "map", "ticket"]],
        "scene_detail": [["chalkboard", "desk", "sunbeam"], ["painting", "sculpture", "spotlight"]],
        "lookup_terms": ["classroom", "museum", "notebook"],
    },
    {
        "id": "nature_expedition",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo", "animal_focus", "scenery"],
        "scene_ids": ["bamboo_forest", "snowy_mountain", "desert_oasis", "volcanic_landscape", "waterfall_gorge", "autumn_park", "greenhouse"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene", "style_light"],
        "tags": ["outdoors", "exploration"],
        "outfit": [["hiking_boots", "backpack"], ["coat", "scarf"], ["traveling_clothes", "gloves"]],
        "action": [["hiking", "looking_forward"], ["taking_photo", "camera"], ["resting", "smile"]],
        "interaction": [["pointing", "looking_at_another"], ["helping_hand", "smile"], ["walking_together", "trail"]],
        "prop": [["map", "compass", "water_bottle"], ["camera", "walking_stick", "bag"], ["flower", "leaf", "notebook"]],
        "scene_detail": [["trail", "rocks", "distant_mountains"], ["mist", "sunbeam", "wind"]],
        "lookup_terms": ["hiking", "compass", "waterfall"],
    },
    {
        "id": "underwater_visit",
        "weight": 2,
        "subject_ids": ["solo_girl", "solo_boy", "duo", "animal_focus", "scenery"],
        "scene_ids": ["aquarium_tunnel", "coral_reef", "seaside_evening"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "prop", "scene", "style_light"],
        "tags": ["aquatic"],
        "outfit": [["casual", "shorts"], ["sailor_collar", "ribbon"], ["swimsuit", "coverup"]],
        "action": [["watching_fish", "smile"], ["pointing_up", "wonder"], ["floating", "relaxed"]],
        "interaction": [["showing_fish", "laughing"], ["looking_at_another", "smile"], ["holding_hands", "blue_light"]],
        "prop": [["fish", "bubble", "shell"], ["jellyfish", "camera", "glass"], ["coral", "seaweed", "water"]],
        "scene_detail": [["blue_light", "caustics", "reflection"], ["glass_tunnel", "school_of_fish", "water"]],
        "lookup_terms": ["aquarium", "coral reef", "jellyfish"],
    },
    {
        "id": "space_expedition",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo", "scenery"],
        "scene_ids": ["space_station", "starship_bridge", "lunar_base", "alien_market", "alien_biodome"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "style_light"],
        "tags": ["space", "science_fiction"],
        "outfit": [["spacesuit", "helmet"], ["pilot_suit", "gloves"], ["jacket", "headset"]],
        "action": [["floating", "reaching_out"], ["operating_console", "focused"], ["exploring", "looking_forward"]],
        "interaction": [["team_pose", "monitor"], ["passing_tool", "focused"], ["pointing_at_planet", "wonder"]],
        "prop": [["helmet", "control_panel", "hologram"], ["rover", "antenna", "tablet_pc"], ["crystal", "sample_container", "toolbox"]],
        "scene_detail": [["earth", "stars", "window"], ["airlock", "screen_glow", "warning_light"]],
        "lookup_terms": ["spacesuit", "starship", "lunar base"],
    },
    {
        "id": "machine_lab",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo", "scenery"],
        "scene_ids": ["robot_factory", "sci_fi_workshop", "alien_biodome"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "style_light"],
        "tags": ["technology", "machine"],
        "outfit": [["lab_coat", "goggles"], ["mechanic_clothes", "gloves"], ["bodysuit", "jacket"]],
        "action": [["repairing_machine", "focused"], ["holding_tool", "kneeling"], ["checking_screen", "serious"]],
        "interaction": [["passing_tool", "looking_at_another"], ["discussing_plan", "monitor"], ["team_pose", "robot"]],
        "prop": [["robot_arm", "toolbox", "cable"], ["wrench", "tablet_pc", "blueprint"], ["control_panel", "mechanical_parts", "sparks"]],
        "scene_detail": [["assembly_line", "metal_floor", "steam"], ["workbench", "screen_glow", "warning_sign"]],
        "lookup_terms": ["robot arm", "mechanic", "blueprint"],
    },
    {
        "id": "fantasy_landmark",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo", "scenery", "animal_focus"],
        "scene_ids": ["arcane_library", "floating_island", "dragon_cave", "sky_castle", "enchanted_garden", "crystal_cavern"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene", "style_light"],
        "tags": ["fantasy", "magic"],
        "outfit": [["cloak", "boots"], ["robe", "wide_sleeves"], ["armor", "cape"]],
        "action": [["casting_spell", "dynamic_pose"], ["holding_lantern", "looking_forward"], ["reaching_out", "wonder"]],
        "interaction": [["showing_map", "smile"], ["protective_stance", "determined"], ["looking_at_another", "curious"]],
        "prop": [["staff", "spellbook", "magic_circle"], ["lantern", "map", "crystal"], ["sword", "shield", "satchel"]],
        "scene_detail": [["rune", "floating_particles", "glowing"], ["tower", "waterfall", "clouds"]],
        "lookup_terms": ["fantasy", "spellbook", "crystal cavern"],
    },
    {
        "id": "dungeon_adventure",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo", "scenery"],
        "scene_ids": ["dungeon_corridor", "treasure_room", "airship_deck", "boss_arena", "fantasy_ruins"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene"],
        "tags": ["adventure", "rpg"],
        "outfit": [["adventurer", "cloak", "boots"], ["armor", "gloves"], ["traveling_clothes", "belt"]],
        "action": [["holding_sword", "determined"], ["opening_chest", "surprised"], ["running", "dynamic_pose"]],
        "interaction": [["team_pose", "serious"], ["pointing", "looking_at_another"], ["protective_stance", "determined"]],
        "prop": [["sword", "shield", "torch"], ["treasure_chest", "map", "key"], ["rope", "compass", "scroll"]],
        "scene_detail": [["stone_wall", "torch", "shadow"], ["gold", "pillar", "cracked_floor"]],
        "lookup_terms": ["dungeon", "treasure chest", "sword"],
    },
    {
        "id": "celebration_event",
        "weight": 3,
        "subject_ids": ["solo_girl", "solo_boy", "duo"],
        "scene_ids": ["parade_street", "wedding_garden", "festival_night", "stage_performance", "market_bazaar"],
        "association_max": 4,
        "association_slots": ["pose_action", "expression", "clothing", "prop", "scene"],
        "tags": ["celebration"],
        "outfit": [["dress", "flower"], ["suit", "necktie"], ["yukata", "hair_ornament"]],
        "action": [["waving", "big_smile"], ["holding_bouquet", "smile"], ["throwing_confetti", "laughing"]],
        "interaction": [["holding_hands", "smile"], ["group_pose", "laughing"], ["dancing", "looking_at_another"]],
        "prop": [["bouquet", "ribbon", "confetti"], ["balloon", "flag", "banner"], ["cake", "flower_arch", "lantern"]],
        "scene_detail": [["crowd", "streamer", "colorful"], ["garden", "chair", "soft_light"]],
        "lookup_terms": ["celebration", "bouquet", "parade"],
    },
])

RANDOM_SFW_OPTIONAL_SLOT_CHANCES = {
    "atmosphere": 0.7,
    "style": 0.65,
}

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
    {
        "id": "dev_nsfw_love_hotel_pair",
        "weight": 2,
        "subject_id": "duo",
        "character_chance": 0.6,
        "copyright_chance": 0.35,
        "lighting_chance": 0.25,
        "association_max": 2,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["sex", "love_hotel", "cum"],
        "tags": ["1girl", "1boy", "sex", "love_hotel"],
        "setting": [
            ["love_hotel", "bed", "colored_lighting"],
            ["hotel_room", "window", "city_lights"],
            ["bathroom", "bathtub", "steam"],
            ["karaoke_room", "sofa", "microphone"],
            ["balcony", "night", "curtains"],
        ],
        "pose": [["cowgirl_position", "straddling"], ["sitting", "legs_apart"], ["lying", "legs_up"]],
        "action": [["sex", "vaginal", "penetration"], ["panties_aside", "grabbing_hips", "penetration"], ["breast_grab", "kissing"]],
        "expression": [["orgasm", "open_mouth", "blush"], ["ahegao", "heavy_breathing"], ["half-closed_eyes", "tears"]],
        "body_detail": [["pussy", "penis", "wet_pussy"], ["cum", "cum_on_body", "nipples"]],
        "finish_detail": [["cum", "cum_in_pussy", "cumdrip"], ["after_sex", "messy_hair", "cum_on_body"]],
        "lighting": [["colored_lighting", "low_light"], ["city_lights", "rim_lighting"]],
    },
    {
        "id": "dev_nsfw_office_after_hours",
        "weight": 2,
        "subject_id": "duo",
        "character_chance": 0.55,
        "copyright_chance": 0.35,
        "lighting_chance": 0.2,
        "association_max": 2,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["office", "sex", "panties_aside"],
        "tags": ["1girl", "1boy", "sex", "office"],
        "setting": [
            ["office", "desk", "night"],
            ["meeting_room", "table", "window"],
            ["storage_room", "shelf", "low_light"],
            ["archive_room", "bookshelf", "desk"],
            ["elevator", "mirror", "indoors"],
        ],
        "pose": [["bent_over", "looking_back"], ["sitting", "spread_legs"], ["standing", "against_wall"]],
        "action": [["panties_aside", "penetration", "grabbing_hips"], ["sex", "vaginal", "desk"], ["shirt_lift", "breast_grab"]],
        "expression": [["orgasm", "open_mouth", "blush"], ["heavy_breathing", "half-closed_eyes"], ["embarrassed", "tears"]],
        "body_detail": [["pussy", "penis", "wet_pussy"], ["nipples", "thighs", "ass"]],
        "finish_detail": [["cum", "cum_on_clothes"], ["after_sex", "disheveled_clothes"], ["cumdrip", "messy_hair"]],
        "lighting": [["office_lighting", "low_light"], ["window_light", "city_lights"]],
    },
    {
        "id": "dev_nsfw_public_tease",
        "weight": 2,
        "subject_id": "solo_girl",
        "character_chance": 0.7,
        "copyright_chance": 0.45,
        "lighting_chance": 0.2,
        "association_max": 3,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["no_panties", "clothes_lift", "flashing"],
        "tags": ["1girl", "solo", "no_panties", "clothes_lift"],
        "setting": [
            ["train_interior", "window", "handrail"],
            ["elevator", "mirror", "indoors"],
            ["rooftop", "railing", "cityscape"],
            ["alley", "street_lamp", "night"],
            ["festival", "lantern", "crowd_blur"],
        ],
        "pose": [["standing", "skirt_lift"], ["sitting", "spread_legs"], ["from_behind", "looking_back"]],
        "action": [["clothes_lift", "flashing"], ["skirt_lift", "no_panties"], ["shirt_lift", "no_bra"]],
        "expression": [["teasing_smile", "looking_at_viewer"], ["embarrassed", "blush"], ["open_mouth", "heavy_breathing"]],
        "body_detail": [["pussy", "cameltoe"], ["nipples", "underboob"], ["thighs", "ass"]],
        "finish_detail": [["wet_pussy", "pussy_juice"], ["after_sex", "disheveled_clothes"], ["cum", "cum_on_clothes"]],
        "lighting": [["street_lamp", "low_light"], ["lantern_light", "rim_lighting"]],
    },
    {
        "id": "dev_nsfw_locker_room_wet",
        "weight": 2,
        "subject_id": "solo_girl",
        "character_chance": 0.65,
        "copyright_chance": 0.4,
        "lighting_chance": 0.25,
        "association_max": 3,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["towel", "wet_clothes", "no_bra"],
        "tags": ["1girl", "solo", "wet_clothes", "towel"],
        "setting": [
            ["locker_room", "locker", "bench"],
            ["gym", "locker_room", "mirror"],
            ["shower_room", "tile_floor", "steam"],
            ["pool", "wet", "water"],
            ["bathhouse", "steam", "towel"],
        ],
        "pose": [["standing", "towel"], ["sitting", "legs_apart"], ["leaning_forward", "looking_at_viewer"]],
        "action": [["towel_lift", "no_bra"], ["wet_shirt", "clothes_lift"], ["panties_aside", "hand_between_legs"]],
        "expression": [["blush", "open_mouth"], ["teasing_smile", "looking_at_viewer"], ["orgasm", "half-closed_eyes"]],
        "body_detail": [["nipples", "erect_nipples"], ["pussy", "wet_pussy"], ["thighs", "underboob"]],
        "finish_detail": [["wet_pussy", "pussy_juice"], ["cum", "cum_on_body"], ["after_sex", "messy_hair"]],
        "lighting": [["steam", "diffused_light"], ["fluorescent_light", "soft_shadow"]],
    },
    {
        "id": "dev_nsfw_outdoor_night",
        "weight": 2,
        "subject_id": "solo_girl",
        "character_chance": 0.65,
        "copyright_chance": 0.4,
        "lighting_chance": 0.2,
        "association_max": 3,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["outdoors", "nude", "clothes_lift"],
        "tags": ["1girl", "solo", "nude", "outdoors"],
        "setting": [
            ["beach", "night", "moonlight"],
            ["forest", "moonlight", "grass"],
            ["camping", "tent", "lantern"],
            ["rooftop", "night", "railing"],
            ["hot_spring", "steam", "rocks"],
        ],
        "pose": [["standing", "covering_breasts"], ["sitting", "spread_legs"], ["kneeling", "looking_at_viewer"]],
        "action": [["clothes_lift", "breast_grab"], ["panties_aside", "touching_self"], ["nude", "covering"]],
        "expression": [["embarrassed", "blush"], ["teasing_smile", "looking_at_viewer"], ["open_mouth", "heavy_breathing"]],
        "body_detail": [["pussy", "nipples"], ["wet_pussy", "thighs"], ["underboob", "ass"]],
        "finish_detail": [["cum", "cum_on_body"], ["wet_pussy", "pussy_juice"], ["after_sex", "messy_hair"]],
        "lighting": [["moonlight", "rim_lighting"], ["lantern_light", "soft_shadow"]],
    },
    {
        "id": "dev_nsfw_fantasy_private",
        "weight": 2,
        "subject_id": "solo_girl",
        "character_chance": 0.65,
        "copyright_chance": 0.4,
        "lighting_chance": 0.25,
        "association_max": 3,
        "association_slots": ["pose", "expression", "body_detail", "prop", "clothing"],
        "trigger_tags": ["fantasy", "nude", "magic_circle"],
        "tags": ["1girl", "solo", "fantasy", "nude"],
        "setting": [
            ["shrine", "torii", "lantern"],
            ["temple", "altar", "candle"],
            ["ruins", "magic_circle", "glowing"],
            ["greenhouse", "flowers", "vines"],
            ["cave", "crystal", "water"],
        ],
        "pose": [["kneeling", "spread_legs"], ["standing", "clothes_lift"], ["sitting", "legs_apart"]],
        "action": [["clothes_lift", "breast_grab"], ["panties_aside", "wet_pussy"], ["touching_self", "open_mouth"]],
        "expression": [["orgasm", "open_mouth", "blush"], ["ahegao", "half-closed_eyes"], ["teasing_smile", "looking_at_viewer"]],
        "body_detail": [["pussy", "nipples"], ["wet_pussy", "thighs"], ["underboob", "pubic_hair"]],
        "finish_detail": [["cum", "cum_on_body"], ["wet_pussy", "pussy_juice"], ["after_sex", "disheveled_clothes"]],
        "lighting": [["candlelight", "warm_light"], ["magic_circle", "blue_glow"]],
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


def _random_prompt_association_tags(current_tags, rng, max_count=5, allowed_slots=None):
    by_trigger = _random_prompt_association_rows()
    if not by_trigger:
        return []
    allowed_slot_keys = {
        _prompt_lookup_norm(slot)
        for slot in allowed_slots or []
        if _prompt_lookup_norm(slot)
    }
    current_norms = {_prompt_lookup_norm(tag) for tag in current_tags if _prompt_lookup_norm(tag)}
    picked = []
    picked_slots = set()
    candidates = []
    for trigger in current_norms:
        for row in by_trigger.get(trigger, [])[:18]:
            related = row.get("related")
            slot = row.get("slot")
            if allowed_slot_keys and _prompt_lookup_norm(slot) not in allowed_slot_keys:
                continue
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


def _profile_id_matches(value, allowed_values):
    allowed = {_prompt_lookup_norm(item) for item in allowed_values or [] if _prompt_lookup_norm(item)}
    if not allowed:
        return True
    return _prompt_lookup_norm(value) in allowed


def _pick_sfw_theme_profile(rng, subject_id, scene_id):
    subject_matches = [
        profile
        for profile in RANDOM_SFW_THEME_PROFILES
        if _profile_id_matches(subject_id, profile.get("subject_ids"))
    ]
    scene_matches = [
        profile
        for profile in subject_matches
        if _profile_id_matches(scene_id, profile.get("scene_ids"))
    ]
    return _pick_weighted_profile(rng, scene_matches or subject_matches or RANDOM_SFW_THEME_PROFILES)


def _extend_tag_group(tags, slots, slot_name, values):
    clean_values = [item for item in values or [] if _clean_text(item)]
    if not clean_values:
        return
    tags.extend(clean_values)
    slots.append({"slot": slot_name, "values": clean_values})


def _random_prompt_lookup_terms(rng, subject, scene, theme=None):
    terms = []
    values = []
    values.extend(subject.get("lookup_terms") or [])
    values.extend(scene.get("lookup_terms") or [])
    if isinstance(theme, dict):
        values.extend(theme.get("lookup_terms") or [])
    for value in values:
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
    theme = _pick_sfw_theme_profile(rng, subject.get("id"), scene.get("id"))
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
    _extend_tag_group(prompt_tags, picked_slots, "theme", theme.get("tags"))
    _extend_tag_group(prompt_tags, picked_slots, "theme_outfit", _pick_group(rng, theme.get("outfit")))
    _extend_tag_group(prompt_tags, picked_slots, "action", _pick_group(rng, subject.get("action")))
    _extend_tag_group(prompt_tags, picked_slots, "theme_action", _pick_group(rng, theme.get("action")))
    _extend_tag_group(prompt_tags, picked_slots, "interaction", _pick_group(rng, theme.get("interaction")))
    _extend_tag_group(prompt_tags, picked_slots, "setting", scene.get("tags"))
    _extend_tag_group(prompt_tags, picked_slots, "scene_detail", _pick_group(rng, scene.get("details")))
    _extend_tag_group(prompt_tags, picked_slots, "theme_scene_detail", _pick_group(rng, theme.get("scene_detail")))
    _extend_tag_group(prompt_tags, picked_slots, "prop", _pick_group(rng, theme.get("prop")))
    _extend_tag_group(prompt_tags, picked_slots, "lighting", _pick_group(rng, scene.get("lighting")))
    _extend_tag_group(prompt_tags, picked_slots, "composition", _pick_group(rng, RANDOM_COMPOSITION_GROUPS.get(composition_key)))
    if rng.random() <= _safe_float(RANDOM_SFW_OPTIONAL_SLOT_CHANCES.get("atmosphere"), 1.0):
        _extend_tag_group(prompt_tags, picked_slots, "atmosphere", _pick_group(rng, RANDOM_ATMOSPHERE_GROUPS))
    if rng.random() <= _safe_float(RANDOM_SFW_OPTIONAL_SLOT_CHANCES.get("style"), 1.0):
        _extend_tag_group(prompt_tags, picked_slots, "style", _pick_group(rng, RANDOM_STYLE_GROUPS))

    for term in _random_prompt_lookup_terms(rng, subject, scene, theme):
        tags = _lookup_prompt_tags(term, source_mode=source_mode, rng=rng, max_count=1)
        if tags:
            lookup_terms.append(term)
            _extend_tag_group(prompt_tags, picked_slots, "danbooru_related", tags)

    association_tags = _random_prompt_association_tags(
        prompt_tags,
        rng,
        max_count=max(0, _safe_int(theme.get("association_max"), 5)),
        allowed_slots=theme.get("association_slots"),
    )
    _extend_tag_group(prompt_tags, picked_slots, "association_stats", association_tags)

    _extend_tag_group(prompt_tags, picked_slots, "quality", RANDOM_QUALITY_TAGS)

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
                "theme": theme.get("id"),
                "character": character_tags[:1],
            },
            "source": "local_prompt_recipe_danbooru_lookup",
        },
    }
