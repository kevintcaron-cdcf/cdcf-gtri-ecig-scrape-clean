"""
policy_rules.py

Deterministic post-classification rules for the MERGED pipeline.

Design principle:
    The Old Prompt is strong on Disposable System and combination devices, so these
    rules do not broadly demote a model "Disposable System" answer. The only
    demotions are hard 510-cartridge / e-nail / dab-tool accessory policies and the
    three evidence-gated reusable-product policies below. The Current Prompt's broad
    Disposable demotions (generic refillable wording, empty liquid status, or a
    "conventional pod system") caused the JNR Stellarc / Lost Mary Nera / Tyson /
    Suorin regressions and are deliberately NOT ported.

Rules ported from the Current Prompt (loosened where they hurt priority categories):
    R1  Closed Refills -> Accessories when there is no liquid evidence (loosened:
        nicotine strength / puff count / "disposable" all count as liquid evidence)
    R2  Closed Refills -> Disposable System for a pod with its OWN battery
        (labeling rule: a pod with its own battery is a Disposable even if it needs a
        separate device to recharge; a Closed Refill has no battery of its own)
    R3  Accessories -> Open System for an operational standalone box/regulated mod
    R4  Open/Closed System -> Accessories when the NAME identifies a standalone
        tank / RTA / RDA / atomizer / coil / replacement pod / cell / charger
    R5  510 cartridge system, e-nail, dab tool -> Accessories
    R6  Accessories -> Closed Refills for a pod with explicit prefilled wording
    R7  Closed Refills -> Nicotine Pouches (safety net)
    R8  Category name normalisation ("Closed Systems" -> "Closed System", ...)
    R9  Final combination_device reconciliation (only a Disposable may be a combo;
        modular-disposable wording turns the flag on)
    R10 Disposable -> Closed Refills only for a prefilled pod/capsule-only listing
        with explicit host-dependency or pod-only package evidence
    R11 Disposable -> Closed System only for a reusable powered host with an explicit
        prefilled-consumable replacement lifecycle
    R12 Disposable -> Open System only for a complete device explicitly intended for
        repeated customer refills with bottled e-liquid
    CBD guard: a CBD-filter positive with no cannabinoid term anywhere in the text is
        sent on to the classifier instead of being routed to CBD.

Standard library only, so it can be imported by the GPU pipeline AND by
offline_eval.py on a laptop without torch/transformers/langfuse.
"""

import re

# ---------------------------------------------------------------------------
# Category names
# ---------------------------------------------------------------------------
DISPOSABLE = "Disposable System"
CLOSED_REFILLS = "Closed Refills"
CLOSED_SYSTEM = "Closed System"
OPEN_SYSTEM = "Open System"
ACCESSORIES = "Accessories"
E_LIQUID = "E-Liquid"
NICOTINE_POUCHES = "Nicotine Pouches"
CONCENTRATE_VAPORIZERS = "Concentrate Vaporizers"
CBD = "CBD"

# R8: canonical spelling of the pipeline's own output. Evaluation-time collapsing
# (Concentrate Vaporizers -> accessories) lives in offline_eval.py, so raw pipeline
# output still distinguishes vaporizers from accessories.
CATEGORY_ALIASES = {
    "closed systems": CLOSED_SYSTEM,
    "closed system": CLOSED_SYSTEM,
    "closed refill": CLOSED_REFILLS,
    "closed refills": CLOSED_REFILLS,
    "disposable": DISPOSABLE,
    "disposables": DISPOSABLE,
    "disposable system": DISPOSABLE,
    "disposable systems": DISPOSABLE,
    "open systems": OPEN_SYSTEM,
    "open system": OPEN_SYSTEM,
    "accessory": ACCESSORIES,
    "accessories": ACCESSORIES,
    "e-liquid": E_LIQUID,
    "e-liquids": E_LIQUID,
    "eliquid": E_LIQUID,
    "concentrate vaporizer": CONCENTRATE_VAPORIZERS,
    "concentrate vaporizers": CONCENTRATE_VAPORIZERS,
    "heated tobacco product": "Heated Tobacco Products",
    "heated tobacco products": "Heated Tobacco Products",
    "nicotine pouch": NICOTINE_POUCHES,
    "nicotine pouches": NICOTINE_POUCHES,
    "cigar": "Cigars",
    "cigars": "Cigars",
    "cbd": CBD,
}

# Rules only ever touch device-like categories.
OVERRIDABLE_CATEGORIES = {
    ACCESSORIES, CLOSED_REFILLS, CLOSED_SYSTEM, DISPOSABLE, OPEN_SYSTEM,
    CONCENTRATE_VAPORIZERS,
}

# ---------------------------------------------------------------------------
# Patterns (all matched against lowercased text)
# ---------------------------------------------------------------------------
# R5 - hard accessory policies. "510 thread" alone is deliberately excluded: it is a
# generic connector reference used by tanks and mods.
CARTRIDGE_510_PATTERNS = (
    r"510[\s-]*(?:thread(?:ed)?[\s-]*)?carts?\b",
    r"510[\s-]*(?:thread(?:ed)?[\s-]*)?cartridges?\b",
    r"\b510[\s-]*(?:cart(?:ridge)?[\s-]*)?batter(?:y|ies)\b",
    r"\bbatter(?:y|ies)\s+(?:for|with)\s+510\b",
    r"\b(?:accepts?|fits?|takes?|works?\s+with|compatible\s+with)\s+"
    r"(?:any\s+)?510[\s-]*(?:thread(?:ed)?\s*)?(?:carts?|cartridges?)\b",
    r"\bmagnetic\s+(?:recessed\s+)?510\s+connection\b",
    r"\b510\s+oil\s+cartridges?\b",
)

ENAIL_PATTERNS = (
    r"\be[\s-]*nails?\b",
    r"\belectric\s+nails?\b",
    r"\bnail\s+kits?\b",
)

DAB_TOOL_TITLE_PATTERNS = (
    r"\bdab\s+knif(?:e|ves)\b",
    r"\bdab\s+tools?\b",
    r"\bdabbers?\b",
    r"\bcarb\s+caps?\b",
    r"\bloading\s+tools?\b",
)

# Liquid evidence. R1 uses the LOOSE set (any of these); R6 requires STRICT wording.
PREFILLED_STRICT_PATTERNS = (
    r"\bpre[\s-]?filled\b",
    r"\bpre[\s-]?fill\b",
    r"\bfilled\s+with\b",
    r"\balready\s+filled\b",
    r"\bnon[\s-]?refillable\b",
    r"\b(?:contains?|comes?\s+with|offers?)\s+\d+(?:\.\d+)?\s*ml\s+(?:of\s+)?"
    r"(?:e-?|vape\s+)?(?:liquid|juice)\b",
    r"\b\d+(?:\.\d+)?\s*ml\s+(?:of\s+)?(?:e-?|vape\s+)?(?:liquid|juice)\s+"
    r"(?:with|per|in)\s+(?:each\s+)?(?:pods?|cartridges?)\b",
)

NICOTINE_STRENGTH_PATTERNS = (
    r"\b\d+(?:\.\d+)?\s*%\s*(?:\(\s*\d+\s*mg|nic|salt|strength)",
    r"\bnicotine(?:\s+(?:strength|percentage|level))?\s*[:\-]?\s*\d+(?:\.\d+)?\s*(?:%|mg)",
    r"\b\d+(?:\.\d+)?\s*(?:%|mg(?:/ml)?)\s+(?:of\s+)?(?:nicotine|nic\b|salt)",
    # bare small percentage such as "5%" / "2.4%" (GetPop Pods Virginia 5%); capped at
    # 0-6% so "100% leak-proof" or "70% VG" is not read as nicotine strength.
    r"(?<![\d.])[0-6](?:\.\d)?\s*%(?![\d])",
    r"(?<![\d.])\d{1,2}\s*mg\b",
)

PUFF_COUNT_PATTERNS = (
    r"\b\d{1,3}(?:[,.]\d{3})+\s*\+?\s*puffs?\b",
    r"\b\d+(?:\.\d+)?\s*k\s*\+?\s*puffs?\b",
    r"\b\d{3,6}\s*\+?\s*puffs?\b",
    r"\bpuffs?\s*(?:count)?\s*[:\-]\s*(?:up\s+to\s+)?\d",
    r"\bmax\s+puffs?\b",
)

# "30K" / "40K" style puff counts in the product NAME only (too noisy in descriptions).
NAME_PUFF_K_PATTERNS = (
    r"\b\d{1,3}k\b",
)

DISPOSABLE_WORD_PATTERNS = (
    r"\bdisposables?\b",
)

# Empty / customer-fillable hardware (blocks R6, triggers R1).
EMPTY_REFILLABLE_PATTERNS = (
    r"\bempty\s+(?:pods?|cartridges?|tanks?)\b",
    r"\b(?:pods?|cartridges?)\s+(?:are|is)\s+empty\b",
    r"\bre-?fillable\b",
    r"\bfillable\b",
    r"\b(?:top|side|bottom)[\s-]*fill(?:ing|ed)?\b",
    r"\bfill[\s-]*(?:system|port|opening|plug|slot|hole)\b",
    r"\brefill(?:ed)?\s+(?:from|through|via)\s+the\b",
    r"\bfill\s+(?:it\s+)?(?:with|your\s+own)\b",
    r"\bpod\s+shells?\b",
    r"\bunfilled\b",
    r"\baccommodat(?:e|es|ing)\s+\d+(?:\.\d+)?\s*ml\b",
    r"\bprime\s+(?:the\s+|each\s+|your\s+)?(?:coils?|pods?)\b",
    r"(?<![\d.])0\s*ml\b",
)

# Negated refillability ("non-refillable", "not refillable", "no refilling") is SEALED
# evidence, not empty evidence. These phrases are blanked before EMPTY_REFILLABLE runs.
NEGATED_REFILL_PATTERNS = (
    r"\b(?:non|not|never)[\s-]+re-?fill(?:able|ed|ing)?\b",
    r"\bno\s+(?:need\s+(?:for|to)\s+)?(?:\w+\s+(?:or|and)\s+)?re-?fill(?:s|ing|able)?\b",
    r"\bcannot\s+be\s+re-?filled\b",
    r"\bwithout\s+(?:the\s+need\s+(?:for|to)\s+)?re-?fill(?:ing)?\b",
)

# Coil / resistance specs: a strong "empty hardware" hint for a pod sold alone.
COIL_SPEC_PATTERNS = (
    r"\b\d+(?:\.\d+)?\s*(?:-\s*)?(?:ohm|Î©)",
    r"\bcoils?\b",
)

# R2 - a pod that carries its OWN battery.
OWN_BATTERY_PATTERNS = (
    r"\b\d+(?:\.\d+)?\s*mah\b",
    r"\bbuilt[\s-]*in\s+batter(?:y|ies)\b",
    r"\bintegrated\s+(?:\d+\s*mah\s+)?(?:rechargeable\s+)?batter(?:y|ies)\b",
)

# R2 also requires wording that the separate device/battery is (only) for RECHARGING
# the pod, e.g. Off-Stamp "Rechargeable via Off Stamp X-Cube Kit Battery Only" or BRK
# "requires the BRK Battery for recharging". An mAh figure alone is not enough, since
# refill-pod listings often print the HOST device's battery (Lost Mary Nera Fullview
# refill pods show "Battery: 800mAh" but are labeled Closed Refills).
RECHARGE_VIA_SEPARATE_PATTERNS = (
    r"\brecharg(?:e|ed|ing|eable)\s+(?:via|with|using|through|on|by)\b.{0,60}"
    r"\b(?:battery|device|kit|base|portion|power\s+pack)\b",
    r"\b(?:requires?|needs?)\b.{0,60}\b(?:battery|device|base)\b.{0,20}"
    r"\bfor\s+recharg(?:e|ing)\b",
    r"\b(?:battery|device|base)\s+(?:needed|required)\s+for\s+recharg(?:e|ing)\b",
    r"\bcharg(?:e|es|ed|ing)\s+(?:via|through|on)\s+the\s+[\w\s-]{0,40}?"
    r"(?:battery|device|base)\b",
)

# Text saying the battery belongs to a DIFFERENT device. Keeps R2 conservative:
# "Battery NOT Included / requires X battery to operate" means the pod has no power.
HOST_BATTERY_ONLY_PATTERNS = (
    r"\bbatter(?:y|ies)\s+(?:is\s+|are\s+)?not\s+included\b",
    r"\brequires?\s+(?:a|an|the)?\s*[\w\s-]{0,40}?batter(?:y|ies)\s+to\s+operate\b",
    r"\bdevice\s+(?:is\s+)?not\s+included\b",
)

# The thing being sold is a pod/cartridge (checked on the NAME).
POD_LISTING_NAME_PATTERNS = (
    r"\bpods?\b",
    r"\bcartridges?\b",
    r"\bcarts?\b",
    r"\bcapsules?\b",
)

KIT_NAME_PATTERNS = (
    r"\bkit\b",
    r"\bstarter\b",
    r"\bdevice\b",
    r"\bsystem\b",
    r"\bmod\b",
)

# R3 - operational standalone mod. The mod wording must be in the product NAME
# (e.g. "DOVPO MVP 220W Box Mod"); description-only mentions such as "pairs with any
# 200W mod" on a tank or charger must not promote an accessory.
STANDALONE_MOD_NAME_PATTERNS = (
    r"\b(?:box|battery|regulated|squonk(?:er)?|tube)\s+mods?\b",
    r"\bmods?\b",
)

OPERATIONAL_MOD_PATTERNS = (
    r"\b\d{2,3}\s*w(?:atts?)?\b",
    r"\b(?:wattage|power|output)\s+(?:range|modes?)\b",
    r"\b(?:temperature|temp)\s+control\b",
    r"\btc\b",
    r"\bvariable\s+(?:voltage|wattage)\b",
    r"\b(?:firing|operating)\s+modes?\b",
    r"\bchip(?:set)?\b",
    r"\bdna\s*\d+",
    r"\b(?:18650|20700|21700)\b",
    r"\bbattery\s+bay\b",
)

# Concentrate / dry-herb context: a "mod" firing quartz/wax atomizers is not an
# e-liquid Open System, so R3 must not promote it (e.g. Yocan UNI Pro, Lookah).
CONCENTRATE_CONTEXT_PATTERNS = (
    r"\bconcentrates?\b",
    r"\bwax\b",
    r"\bdabs?\b",
    r"\bdry\s+herb\b",
    r"\bquartz\b",
    r"\b710\b",
    r"\bnectar\s+collector\b",
    r"\bherbs?\b",
)

# R4 - the product NAME identifies a standalone component.
STANDALONE_COMPONENT_TITLE_PATTERNS = (
    r"\btanks?\b",
    r"\b(?:rta|rda|rdta|rba)s?\b",
    r"\batomi[sz]ers?\b",
    r"\b(?:replacement\s+)?coils?\b",
    r"\b(?:empty|replacement|refillable)\s+(?:pods?|cartridges?)\b",
    r"\bpod\s+cartridges?\b",
    r"\b(?:pods?|cartridges?)\s*\(\s*\d+\s*(?:pcs|pc|pack)",
    r"\(\s*\d+\s*pcs\s*/\s*pack\s*\)",
    r"\b(?:individual|replacement|spare)\s+(?:battery|cell)s?\b",
    r"\b(?:18350|18650|20700|21700|26650)\s*(?:battery|cell)s?\b",
    r"\bchargers?\b",
    r"\bdrip\s+tips?\b",
    r"\bmouthpieces?\b",
)

# A title that ALSO names a complete kit / power device must not be demoted by R4
# (e.g. "SMOK X-PRIV Kit 225W with TFV12 Prince Tank", "Aegis L200 with Z Tank").
COMPLETE_KIT_TITLE_PATTERNS = (
    r"\bkit\b",
    r"\bstarter\b",
    r"\bsystem\b",
    r"\bmods?\b",
    r"\bdevice\b",
    r"\bwith\b",
    r"\b\d{2,3}\s*w\b",
    r"\bmah\b",
)

# R10-R12 - narrow reusable-product evidence. These rules intentionally do NOT use
# site categories, brands, puff counts, generic modularity, or generic "refillable"
# wording as positive evidence. Each rescue needs multiple statements about the role
# of the item being sold that contradict a one-time, complete disposable device.

# A separately sold, prefilled consumable names or requires its host device. This is
# deliberately more specific than magnetic / snap-in wording, which is common on
# modular Disposable Systems too.
POD_HOST_DEPENDENCY_PATTERNS = (
    r"\b(?:refill|replacement)\s+(?:pods?|cartridges?|capsules?)\s+for\b",
    r"\b(?:compatible|works?|for\s+use)\s+with\s+(?:the\s+)?"
    r"(?:[\w-]+\s+){0,5}(?:device|battery|kit|system|vape)\b",
    r"\b(?:requires?|needs?)\s+(?:the\s+)?(?:[\w-]+\s+){0,5}"
    r"(?:device|battery|kit|system)\b",
)

# A pack containing only pods/capsules/cartridges is positive evidence that the
# purchasable unit is a consumable, not a complete device. It is combined with
# explicit prefilled evidence and the pod/capsule name check in R10.
POD_ONLY_PACKAGE_PATTERNS = (
    r"\b(?:comes?\s+in\s+)?(?:a\s+)?pack\s+of\s+(?:\d+|one|two|three|four|five)\b"
    r".{0,60}\b(?:pods?|cartridges?|capsules?)\b",
    r"\b(?:includes?|in\s+the\s+box)\b.{0,60}\b\d+\s*(?:[\w-]+\s+){0,3}"
    r"(?:pods?|cartridges?|capsules?)\b",
)

# A reusable closed system must identify a host that survives the consumable. A bare
# mAh figure or a generic USB port is intentionally excluded because either can occur
# on a disposable. "Detachable battery" is only accepted together with every other
# R11 condition, including an explicit replacement lifecycle.
REUSABLE_HOST_POWER_PATTERNS = (
    r"\b(?:internal|built[\s-]*in|integrated)\s+\d+(?:\.\d+)?\s*mah\s+"
    r"rechargeable\s+batter(?:y|ies)\b",
    r"\b(?:rechargeable|detachable|removable)\s+(?:battery|power\s*pack|host)\b",
)

PREFILLED_CONSUMABLE_PATTERNS = (
    r"\bpre[\s-]?filled\s+(?:disposable\s+)?(?:pods?|cartridges?|capsules?)\b",
    r"\b(?:pods?|cartridges?|capsules?)\s+(?:are\s+)?pre[\s-]?filled\b",
    r"\bpre[\s-]?filled\s+(?:e-?|vape\s+)?(?:liquid|juice)\b",
)

# This is the key R11 guard: the text must say that the consumable is changed after
# use, not merely that a pod is detachable, replaceable, magnetic, or snap-in.
CONSUMABLE_REPLACEMENT_LIFECYCLE_PATTERNS = (
    r"\b(?:replace|swap|change)\s+(?:the\s+)?(?:pod|cartridge|capsule)\s+when\s+"
    r"(?:you\s+are\s+)?(?:done|empty|depleted|finished)\b",
    r"\b(?:easily\s+)?interchangeable\b.{0,60}\bpre[\s-]?filled\b.{0,60}"
    r"\b(?:pods?|cartridges?|capsules?)\b",
    r"\bpre[\s-]?filled\b.{0,60}\b(?:easily\s+)?interchangeable\s+"
    r"(?:pods?|cartridges?|capsules?)\b",
    r"\b(?:replaceable|swappable)\s+(?:pre[\s-]?filled\s+)?"
    r"(?:pods?|cartridges?|capsules?)\s+(?:when\s+)?(?:empty|depleted)\b",
)

# R12 requires all three: a named complete device, a repeated-refill promise, and
# explicit bottled e-liquid as the customer-fill material. This prevents a lone
# refillable pod/tank or generic refillability marketing from becoming Open System.
COMPLETE_DEVICE_NAME_PATTERNS = (
    r"\b(?:vape|device|pen|kit|system)\b",
)

REPEATED_CUSTOMER_REFILL_PATTERNS = (
    r"\b(?:(?:can|may)(?:\s+be)?|designed\s+to\s+be|"
    r"allows?(?:\s+the\s+user)?\s+to\s+be)?\s*"
    r"re[\s-]?filled\s+(?:up\s+to\s+)?(?:\d+|multiple|many|several)\s+times\b",
    r"\b(?:multiple|many|several)\s+re[\s-]?fills?\b",
)

CUSTOMER_E_LIQUID_REFILL_PATTERNS = (
    r"\b(?:re[\s-]?fill|fill)\w*\b.{0,80}\b(?:your\s+(?:favorite|own)\s+)?"
    r"(?:e-?liquid|e-?juice|vape\s+juice)\b",
)

# R7
NICOTINE_POUCH_PATTERNS = (
    r"\bnicotine\s+pouches?\b",
    r"\boral\s+nicotine\b",
    r"\bpouches?\b",
)

# R9 - modular-disposable (combination device) wording. Mirrors the Old Prompt's Rule 4
# keywords plus common listing phrasings seen in the 1500-row sample.
COMBO_MODULARITY_PATTERNS = (
    r"\breplaceable\s+(?:and\s+refillable\s+|pre[\s-]?filled\s+)?pods?\b",
    # Bare "detachable" also matches screens/displays; require a battery/pod noun.
    r"\bdetachable\s+(?:and\s+rechargeable\s+)?(?:\d+\s*mah\s+)?"
    r"(?:smart\s+)?(?:battery|batteries|pod|cartridge|power\s*pack|power\s*bank)\b",
    r"\b(?:battery|pod|cartridge|power\s*bank)s?\s+(?:is\s+|are\s+)?detachable\b",
    r"\bchange\s+(?:the\s+)?pods?\b",
    r"\bmagnetic(?:ally)?\s+(?:attach(?:able|ed)?|connect(?:ion|ed)?|pods?)\b",
    r"\bpod\s+connection\s*[:\-]?\s*magnetic\b",
    r"\bplug[\s-]*(?:and|&|n|'n')[\s-]*play\b",
    r"\bsnap[\s-]*(?:on|in)\b",
    r"\bclicks?\s+into\s+place\b",
    r"\bpod\s+(?:and|&|\+)\s+battery\b",
    r"\bbattery\s+(?:and|&|\+)\s+pod\b",
    r"\b(?:composed|consists?)\s+of\s+(?:a\s+)?replaceable\s+pod\b",
    r"\binterchangeable\s+pods?\b",
    r"\bswap(?:pable)?\s+(?:the\s+)?pods?\b",
    r"\breplacement\s+pods?\s+only\b",
    r"\bbuy(?:ing)?\s+the\s+replacement\s+pod\b",
    r"\bcompatible\s+with\s+the\s+[\w\s-]{0,40}?pre[\s-]?filled\s+pods?\b",
)

# R9b - parts of the model's combo rationale. A rationale that cites only a
# screen/display/cover (and no battery/pod) is not evidence of a combo device.
NON_MODULAR_PART_PATTERNS = (
    r"\bscreens?\b",
    r"\bdisplays?\b",
    r"\bcover(?:\s+plates?)?\b",
)

MODULAR_PART_PATTERNS = (
    r"\bpods?\b",
    r"\bbatter(?:y|ies)\b",
    r"\bpower\s*(?:pack|bank)s?\b",
    r"\bcartridges?\b",
)

# CBD guard - an explicit cannabinoid (or other non-nicotine botanical) term.
CANNABINOID_TERM_PATTERNS = (
    r"\bcbd\b",
    r"\bcbg\b",
    r"\bcbn\b",
    r"\bthc[\w-]*\b",
    r"\bdelta[\s-]?\d+\b",
    r"\bd[89]\b",
    r"\bhhc[\w-]*\b",
    r"\bcannabi\w*\b",
    r"\bhemp\b",
    r"\bmarijuana\b",
    r"\bkratom\b",
    r"\bkava\b",
    r"\bmushroom\w*\b",
    r"\bamanita\b",
    r"\bdistillate\b",
    r"\blive\s+resin\b",
    r"\brosin\b",
    r"\bterpenes?\b",
    # Strain vocabulary: keeps the guard conservative (e.g. "Rinyu Serenity Pod By Kush
    # Kolectiv" stays CBD). The guard only ever RESCUES rows, so false "cannabis" hits here
    # just mean the CBD filter's answer is kept, i.e. the Old behaviour.
    r"\bkush\b",
    r"\bindica\b",
    r"\bsativa\b",
    r"\bstrains?\b",
    r"\bdabs?\b",
    r"\bwax\b",
    r"\bshatter\b",
    r"\bbadder\b",
)

# CBD guard also needs POSITIVE nicotine-vape context before it overrides the CBD filter.
NICOTINE_CONTEXT_PATTERNS = (
    r"\bnicotine\b",
    r"\bnic\b",
    r"\bsalts?\b",
    r"\be-?liquids?\b",
    r"\be-?juices?\b",
    r"\bvape\s+juice\b",
    r"\bvape\b",
    r"\bpuffs?\b",
    r"\bdisposables?\b",
    r"\bthroat\s+hit\b",
    r"\bpod\s+system\b",
)

SOURCE_TEXT_FIELDS = (
    "product_name",
    "site_category",
    "site_tag",
    "description",
    "eliquid_contents",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clean(value):
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.lower() == "nan" else value


def _get(row, key):
    if hasattr(row, "get"):
        return row.get(key, "")
    return ""


_NON_ASCII = re.compile(r"[^\x00-\x7f]+")


def build_source_text(row):
    """Concatenate the classifier's source metadata into one lowercase string.

    Non-ASCII runs are replaced by a space. The scraped descriptions contain mojibake
    bullets (e.g. "200mAhÃ¢â‚¬Å¡Ãƒâ€žÃƒÂ¶"), and Python treats "Ã¢" as a word character, which
    silently breaks every `\\b` boundary next to it.
    """
    parts = [_clean(_get(row, field)) for field in SOURCE_TEXT_FIELDS]
    return _NON_ASCII.sub(" ", " ".join(p for p in parts if p)).lower()


def _any(text, patterns):
    return any(re.search(p, text) for p in patterns)


def normalize_category(category):
    """R8: map model spellings onto the canonical category names."""
    if category is None:
        return ""
    raw = str(category).strip()
    return CATEGORY_ALIASES.get(raw.lower(), raw)


def extract_signals(row):
    """Compute every regex signal once (also handy for debugging a single row)."""
    text = build_source_text(row)
    name = _NON_ASCII.sub(" ", _clean(_get(row, "product_name"))).lower()
    # Blank negated refill phrases so "non-refillable" is not read as "refillable".
    text_no_negation = text
    for pattern in NEGATED_REFILL_PATTERNS:
        text_no_negation = re.sub(pattern, " ", text_no_negation)
    s = {
        "has_510": _any(text, CARTRIDGE_510_PATTERNS),
        "has_enail": _any(text, ENAIL_PATTERNS),
        "name_dab_tool": _any(name, DAB_TOOL_TITLE_PATTERNS),
        "prefilled_strict": _any(text, PREFILLED_STRICT_PATTERNS),
        "nicotine_strength": _any(text, NICOTINE_STRENGTH_PATTERNS),
        "puff_count": _any(text, PUFF_COUNT_PATTERNS) or _any(name, NAME_PUFF_K_PATTERNS),
        "disposable_word": _any(text, DISPOSABLE_WORD_PATTERNS),
        "empty_refillable": _any(text_no_negation, EMPTY_REFILLABLE_PATTERNS),
        "coil_spec": _any(text, COIL_SPEC_PATTERNS),
        "own_battery": _any(text, OWN_BATTERY_PATTERNS),
        "recharge_via_separate": _any(text, RECHARGE_VIA_SEPARATE_PATTERNS),
        "host_battery_only": _any(text, HOST_BATTERY_ONLY_PATTERNS),
        "name_pod_listing": _any(name, POD_LISTING_NAME_PATTERNS),
        "name_kit": _any(name, KIT_NAME_PATTERNS),
        "name_standalone_mod": _any(name, STANDALONE_MOD_NAME_PATTERNS),
        "operational_mod": _any(text, OPERATIONAL_MOD_PATTERNS),
        "concentrate_context": _any(text, CONCENTRATE_CONTEXT_PATTERNS),
        "name_component": _any(name, STANDALONE_COMPONENT_TITLE_PATTERNS),
        "name_complete_kit": _any(name, COMPLETE_KIT_TITLE_PATTERNS),
        "pod_host_dependency": _any(text, POD_HOST_DEPENDENCY_PATTERNS),
        "pod_only_package": _any(text, POD_ONLY_PACKAGE_PATTERNS),
        "reusable_host_power": _any(text, REUSABLE_HOST_POWER_PATTERNS),
        "prefilled_consumable": _any(text, PREFILLED_CONSUMABLE_PATTERNS),
        "consumable_replacement_lifecycle": _any(
            text, CONSUMABLE_REPLACEMENT_LIFECYCLE_PATTERNS),
        "name_complete_device": _any(name, COMPLETE_DEVICE_NAME_PATTERNS),
        "repeated_customer_refill": _any(text, REPEATED_CUSTOMER_REFILL_PATTERNS),
        "customer_e_liquid_refill": _any(text, CUSTOMER_E_LIQUID_REFILL_PATTERNS),
        "nicotine_pouch": _any(text, NICOTINE_POUCH_PATTERNS),
        "combo_wording": _any(text, COMBO_MODULARITY_PATTERNS),
        "cannabinoid_term": _any(text, CANNABINOID_TERM_PATTERNS),
        "nicotine_context": _any(text, NICOTINE_CONTEXT_PATTERNS),
        # Enough description text to judge "no liquid evidence" (R1_NO_LIQUID) and the
        # CBD guard. Name-only / blank listings are left to the model.
        "has_text": len(_NON_ASCII.sub(" ", _clean(_get(row, "description"))).strip()) >= 40,
    }
    s["liquid_evidence_loose"] = (
        s["prefilled_strict"] or s["nicotine_strength"] or s["puff_count"]
        or s["disposable_word"]
    )
    # Labeling rule: a pod with its OWN battery is a Disposable. Require both a battery
    # spec and "recharged via the separate device" wording, and no "battery not included".
    s["self_powered_pod"] = (
        s["own_battery"] and s["recharge_via_separate"] and not s["host_battery_only"]
    )
    return s


def cbd_guard_should_override(row):
    """True when a CBD-filter positive looks like a nicotine product with no cannabinoid
    term anywhere in the listing text.

    Both conditions are required: (1) no cannabinoid/strain term, AND (2) positive
    nicotine-vape context (nicotine, salts, e-liquid, puffs, disposable, vape, ...).
    The 4 CBD false positives in the 1500 sample (Cali XLT 40K, Lost Mary Quasar,
    Epitome Premium Blends Salts, Cosmic Fog Kryptonite) all satisfy both.
    """
    s = extract_signals(row)
    return (not s["cannabinoid_term"]) and s["nicotine_context"] and s["has_text"]


# ---------------------------------------------------------------------------
# Main policy
# ---------------------------------------------------------------------------
def _override(result, category, rule_id, reason):
    result["categories"] = category
    result["post_override_category"] = category
    result["policy_override_applied"] = True
    result["policy_rule_id"] = rule_id
    result["policy_override_reason"] = reason
    result["confidence"] = "low"
    return result


def _mark_self_powered_pod_combo(result):
    result["combination_device"] = True
    result["combination_device_rationale"] = (
        "Self-powered prefilled pod that pairs with a separate device/battery"
    )


def apply_category_policy(result, row):
    """Apply R1-R9 to a parsed classifier result (dict) for one source row.

    Adds: pre_override_category, post_override_category, policy_override_applied,
    policy_rule_id, policy_override_reason, model_rationale. `rationale` is replaced by
    the rule reason only when a rule fires, so the HTML review shows why it changed.
    """
    category = normalize_category(result.get("categories", ""))
    result["categories"] = category
    result["pre_override_category"] = category
    result["post_override_category"] = category
    result["policy_override_applied"] = False
    result["policy_rule_id"] = None
    result["policy_override_reason"] = None
    result.setdefault("model_rationale", result.get("rationale", ""))

    signals = None
    if category in OVERRIDABLE_CATEGORIES:
        signals = extract_signals(row)
        _apply_rules(result, category, signals)
        if result["policy_override_applied"]:
            result["rationale"] = result["policy_override_reason"]

    finalize_combination_flag(result, row, signals=signals)
    return result


def _apply_rules(result, category, s):
    disposable_marketed = s["disposable_word"] and s["puff_count"]

    # ---- R5: hard accessory policies (the only rules allowed to move a Disposable) --
    if category != ACCESSORIES and not disposable_marketed:
        if s["has_510"]:
            return _override(result, ACCESSORIES, "R5_510",
                             "510 cartridge system is Accessories under labeling policy")
        if s["has_enail"]:
            return _override(result, ACCESSORIES, "R5_ENAIL",
                             "E-nail/electric nail is Accessories under labeling policy")
        if s["name_dab_tool"]:
            return _override(result, ACCESSORIES, "R5_DAB_TOOL",
                             "Dab tool/carb cap is Accessories under labeling policy")

    if category == CLOSED_REFILLS:
        return _closed_refill_rules(result, s)
    if category == ACCESSORIES:
        return _accessory_rules(result, s)
    if category == DISPOSABLE:
        return _disposable_rescue_rules(result, s)
    if category in (OPEN_SYSTEM, CLOSED_SYSTEM):
        # R4: the product NAME is a standalone component (tank, RTA, coil, pod pack...).
        # Guard: "Foger Ultra TANK Disposable Vape 6000 Puffs" is a disposable, not a tank.
        if (s["name_component"] and not s["name_complete_kit"]
                and not disposable_marketed):
            return _override(result, ACCESSORIES, "R4_COMPONENT_TITLE",
                             "Product name identifies a standalone component, which is "
                             "Accessories under labeling policy")
    # Concentrate Vaporizers are intentionally untouched here.
    return result


def _disposable_rescue_rules(result, s):
    """Correct only evidence-backed reusable roles miscalled Disposable.

    These are deliberately conjunctive. Generic marketing terms ("disposable",
    puff counts, detachable/magnetic/snap-in, and refillable) cannot fire a rescue
    on their own, protecting true high-puff and modular disposable kits.
    """
    # R10: prefilled consumable sold for a separately named host, or a package that
    # contains only prefilled pods/capsules/cartridges. A pod with its own battery is
    # still a Disposable under R2's labeling rule, so it is explicitly excluded.
    if (s["name_pod_listing"] and s["prefilled_strict"] and not s["self_powered_pod"]
            and (s["pod_host_dependency"] or s["pod_only_package"])):
        return _override(result, CLOSED_REFILLS, "R10_POD_ONLY_REFILL",
                         "Prefilled pod/capsule listing is a consumable for a separate host, "
                         "not a complete Disposable System")

    # R11: the rechargeable/detachable host and the prefilled consumable's replacement
    # lifecycle must both be explicit. A prefilled modular disposable with a separated
    # battery but no reusable-consumable lifecycle does not qualify.
    # Tightened: require the explicit replace-when-depleted lifecycle AND a reusable
    # host (not merely "interchangeable" wording on a single-use disposable).
    if (s["reusable_host_power"] and s["prefilled_consumable"]
            and s["consumable_replacement_lifecycle"] and not s["self_powered_pod"]):
        return _override(result, CLOSED_SYSTEM, "R11_REUSABLE_CLOSED_HOST",
                         "Reusable powered host has an explicit prefilled-pod/capsule "
                         "replacement lifecycle")

    # R12: a complete device must promise repeated customer refills and identify
    # bottled e-liquid as the fill material. "Refillable" alone is not enough.
    if (s["name_complete_device"] and not s["name_component"]
            and not s["concentrate_context"] and not s["has_510"]
            and s["repeated_customer_refill"] and s["customer_e_liquid_refill"]):
        return _override(result, OPEN_SYSTEM, "R12_REPEATED_E_LIQUID_REFILL",
                         "Complete device is explicitly intended for repeated customer refills "
                         "with e-liquid")
    return result


def _closed_refill_rules(result, s):
    # R7: nicotine pouches mis-routed to Closed Refills.
    if s["nicotine_pouch"] and not s["name_pod_listing"]:
        return _override(result, NICOTINE_POUCHES, "R7_POUCH",
                         "Nicotine pouch products are not Closed Refills")
    # R2: a pod with its own battery is a Disposable (project labeling rule).
    if (s["self_powered_pod"] and s["liquid_evidence_loose"]
            and not s["empty_refillable"]):
        _override(result, DISPOSABLE, "R2_POD_OWN_BATTERY",
                  "Prefilled pod has its own battery; a pod with its own battery is a "
                  "Disposable System under labeling policy")
        _mark_self_powered_pod_combo(result)
        return result
    # R1: explicit empty / customer-fillable hardware.
    if s["empty_refillable"] and not s["prefilled_strict"]:
        return _override(result, ACCESSORIES, "R1_EMPTY_HARDWARE",
                         "Pod/cartridge is customer-fillable (refillable/fill-port wording) "
                         "with no prefilled evidence")
    # R1: "Replacement Pod Cartridge (3pcs/pack)" + coil/ohm spec = empty hardware.
    if (s["name_component"] and s["coil_spec"] and not s["prefilled_strict"]
            and not s["disposable_word"] and not s["puff_count"]):
        return _override(result, ACCESSORIES, "R1_REPLACEMENT_POD",
                         "Replacement pod cartridge with coil/ohm spec and no prefilled "
                         "evidence is empty hardware")
    # R1: no liquid evidence at all (only when there is enough description to judge).
    if not s["liquid_evidence_loose"] and s["has_text"]:
        return _override(result, ACCESSORIES, "R1_NO_LIQUID",
                         "Closed Refills requires liquid evidence (prefilled wording, "
                         "nicotine strength, or puff count)")
    return result


def _accessory_rules(result, s):
    if s["has_510"] or s["has_enail"] or s["name_dab_tool"]:
        return result
    # R3: operational standalone mod -> Open System.
    if (s["name_standalone_mod"] and s["operational_mod"] and not s["concentrate_context"]
            and not s["name_component"] and not s["name_pod_listing"]):
        return _override(result, OPEN_SYSTEM, "R3_OPERATIONAL_MOD",
                         "Operational standalone box/regulated mod is an Open System under "
                         "labeling policy")
    # R6: pod with explicit prefilled wording -> Closed Refills
    # (or Disposable if the pod has its own battery, per the R2 labeling rule).
    if (s["name_pod_listing"] and not s["name_kit"] and not s["name_component"]
            and s["prefilled_strict"]
            and not s["empty_refillable"] and not s["nicotine_pouch"]
            and not s["cannabinoid_term"]):
        if s["self_powered_pod"]:
            _override(result, DISPOSABLE, "R6_POD_OWN_BATTERY",
                      "Prefilled pod with its own battery is a Disposable System under "
                      "labeling policy")
            _mark_self_powered_pod_combo(result)
            return result
        return _override(result, CLOSED_REFILLS, "R6_PREFILLED_POD",
                         "Pod/cartridge has explicit prefilled evidence and no "
                         "empty/refillable wording")
    return result


def finalize_combination_flag(result, row, signals=None):
    """R9: make combination_device consistent with the FINAL category.

    - Non-Disposable rows can never be combination devices (fixes inflated counts).
    - R9a: a self-powered prefilled pod sold for a separate battery/device is a
      combo COMPONENT, not a full combo. It gets combo_component=True and
      combination_device=False, so it stays visible without counting as a combo.
    - R9b: a model combo flag whose only cited evidence is a detachable screen,
      display, or cover is cleared; only battery/pod modularity counts.
    - A Disposable with modular wording is a combination device even if the model
      forgot the flag (mirrors Old Prompt Rule 4's keyword list).
    - Otherwise the model's own True is kept for Disposables (Rule 4 also uses the image).
    """
    category = result.get("categories")
    model_flag = bool(result.get("combination_device"))
    result["model_combination_device"] = model_flag
    result["combo_rule_applied"] = None
    result["combo_component"] = False
    if category != DISPOSABLE:
        if model_flag:
            result["combo_rule_applied"] = "R9_CLEARED_NON_DISPOSABLE"
        result["combination_device"] = False
        result["combination_device_rationale"] = None
        return result
    s = signals if signals is not None else extract_signals(row)
    # R9a: self-powered pod for a separate host -> component flag, not a combo.
    if s["self_powered_pod"] and s["name_pod_listing"] and not s["name_kit"]:
        result["combo_component"] = True
        result["combination_device"] = False
        result["combination_device_rationale"] = (
            "Combo component: self-powered prefilled pod sold for a separate "
            "battery/device; not a complete combination device"
        )
        result["combo_rule_applied"] = "R9A_COMBO_COMPONENT"
        return result
    if model_flag:
        # R9b: clear a model flag whose only cited evidence is a screen/display/cover.
        rationale = str(result.get("combination_device_rationale") or "").lower()
        if (_any(rationale, NON_MODULAR_PART_PATTERNS)
                and not _any(rationale, MODULAR_PART_PATTERNS)):
            result["combination_device"] = False
            result["combination_device_rationale"] = (
                "Cleared: only a detachable screen/display/cover was cited; "
                "combo requires a detachable battery or pod"
            )
            result["combo_rule_applied"] = "R9B_CLEARED_SCREEN_ONLY"
        return result
    if s["combo_wording"]:
        result["combination_device"] = True
        result["combination_device_rationale"] = (
            "Listing text describes a modular pod-and-battery disposable "
            "(replaceable/detachable/magnetic/snap-in pod wording)"
        )
        result["combo_rule_applied"] = "R9_SET_FROM_TEXT"
    return result
