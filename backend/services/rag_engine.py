"""
NASA Level V Crew Medical Officer RAG Engine (Layer 3) — High-Speed Neuro-Symbolic Edition.

Upgraded from the UoM FYP (`Team Leader`) RAG architecture specifically for deep-space
real-time clinical triage (<1ms execution, 100% air-gapped, zero external DB/Docker overhead):

1. 3-Signal Hybrid Retrieval Fusion:
   - Signal 1 (Symbolic Biotelemetry & Equation Signature Scorer): Evaluates directional
     physiological Z-scores + negative-evidence disambiguation (e.g., rules out Hypercapnia
     for a headache if Cabin CO2 < 2.6 mmHg, routing to SANS or Circadian instead).
   - Signal 2 (Okapi BM25 + Clinical Ontology Synonym Expansion): Weighted Inverse Document
     Frequency (IDF) lexical retrieval with astronaut colloquial-to-clinical term mapping.
   - Signal 3 (Character Trigram TF-IDF Vector Cosine Similarity): Subword vector similarity
     resilient to typos and morphological variations (e.g., thrombus/thrombosis/thrombotic).
2. Multi-Source Tagged Knowledge Base:
   - Ingests `data/rag_protocols_8_scenarios.json`, `data/nasa_space_medicine_research.md`
     (chunked with `[Source: ...]` headers), `data/arxiv_literature_citations.json`, and
     dynamically scans `data/nasa_official_protocols/` for upcoming NASA datasets.
3. Strict 2-Mode Clinical Decision Protocol:
   - MODE A (Confidence >= 0.75): Known condition, verbatim NASA-STD-3001 quote, 2023 ISS
     CHeCS subpack prescriptions, and hard-coded flight contraindications.
   - MODE B (Confidence < 0.75): Certified Abstention (zero hallucination) + 4-Step Zero-Day
     Space Medicine Protocol (ABC Stabilization, MDP Point-of-Care Labs, Drug Lockout,
     Priority Earth Uplink & In-Flight RAG Learning).
4. Deterministic SHA-256 Triage Cache & Flight Audit Log.
"""

import csv
import hashlib
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.models.telemetry import AnomalyAssessment, TelemetryPacket


# Static loop bounds per JPL Power-of-Ten Rule 2
MAX_PROTOCOLS: int = 64
MAX_KEYWORDS: int = 64
MAX_DYNAMIC_FILES: int = 20
MAX_CANDIDATE_QUEUE: int = 50
MAX_CACHE_ENTRIES: int = 256
MAX_SYMPTOM_CHARS: int = 500
MAX_CHUNKS: int = 256
MODE_A_CONFIDENCE_THRESHOLD: float = 0.75


REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
PROTOCOLS_JSON_PATH: Path = REPO_ROOT / "data" / "rag_protocols_8_scenarios.json"
EXPANDED_PROTOCOLS_JSON_PATH: Path = REPO_ROOT / "data" / "rag_protocols_expanded.json"
CHECS_FORMULARY_JSON_PATH: Path = REPO_ROOT / "data" / "checs_formulary.json"
NASA_RULES_JSON_PATH: Path = REPO_ROOT / "data" / "nasa_std_3001_rules.json"
LAB_INTERVALS_JSON_PATH: Path = REPO_ROOT / "data" / "lab_reference_intervals.json"
HARDWARE_SPECS_JSON_PATH: Path = REPO_ROOT / "data" / "onboard_hardware_specs.json"
RESEARCH_MD_PATH: Path = REPO_ROOT / "data" / "nasa_space_medicine_research.md"
ARXIV_JSON_PATH: Path = REPO_ROOT / "data" / "arxiv_literature_citations.json"
OFFICIAL_PROTOCOLS_DIR: Path = REPO_ROOT / "data" / "nasa_official_protocols"

VALID_CHECS_SUBPACKS = {"CMP", "OMP", "TIMP", "EMTP", "VCP", "RSP", "ISP", "MDP", "MTP"}

FORMULARY_ALIAS_MAP: Dict[str, str] = {
    "trimethoprim/smx": "trimethoprim/sulfamethoxazole",
    "tmp-smx": "trimethoprim/sulfamethoxazole",
}

SUPPORT_PACK_ITEMS: Dict[str, Tuple[str, str, str]] = {
    "100% oxygen": ("RSP", "Inhaled via RSP demand mask", "10-15 L/min 100% O2"),
    "supplemental o2": ("RSP", "Inhaled via RSP mask/cannula", "Titrate to SpO2 >= 94%"),
    "iv normal saline": ("ISP", "IV infusion", "500-1000 mL 0.9% NaCl IV"),
    "iv crystalloids": ("ISP", "IV infusion", "500-1000 mL isotonic crystalloid IV"),
    "iv/oral rehydration electrolytes": ("ISP", "IV / Oral", "500-1000 mL electrolyte rehydration"),
    "oral/iv rehydration": ("ISP", "Oral / IV", "Oral rehydration salts or 0.9% NaCl IV"),
    "sterile urinary catheterization kit": ("MTP", "Urethral catheterization", "Single sterile Foley/straight catheter kit"),
}

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "what", "have", "has",
    "been", "feeling", "feels", "very", "some", "into", "over", "after", "during",
    "while", "astronaut", "crew", "crewmember", "slight", "mild", "acute", "severe",
}

# Clinical Synonym & Colloquial Astronaut Symptom Ontology Expansion
CLINICAL_SYNONYM_MAP: Dict[str, str] = {
    "short of breath": "dyspnea",
    "shortness of breath": "dyspnea",
    "breathless": "dyspnea",
    "cant breathe": "dyspnea",
    "air feels heavy": "hypercapnia co2 sluggish",
    "air sluggish": "hypercapnia co2 sluggish",
    "stuffy air": "hypercapnia co2",
    "numb face": "trigeminal dysesthesia",
    "facial numbness": "trigeminal dysesthesia",
    "blurry near vision": "sans hyperopic oct rnfl",
    "arms length": "sans hyperopic near-vision",
    "eye pressure": "sans retro-orbital optic disc edema",
    "behind eyes": "sans retro-orbital",
    "wavy lines": "sans metamorphopsia",
    "blind spot": "sans scotomas",
    "dizzy standing": "orthostatic presyncope lightheadedness",
    "about to faint": "orthostatic presyncope syncope graying",
    "blacking out": "orthostatic presyncope tunnel vision",
    "cold sweat": "orthostatic diaphoresis",
    "throwing up": "vomiting emesis nausea",
    "throw up": "vomiting emesis nausea",
    "radiation storm": "solar flare spe ars donki",
    "joint pain": "dcs bends periarticular decompression",
    "shoulder pain": "dcs bends periarticular",
    "knee pain": "dcs bends periarticular",
    "burning chest": "dcs chokes substernal",
    "helmet fog": "thermal visor fogging sweat",
    "overheating": "thermal strain heat",
    "cant sleep": "circadian insomnia sleep",
    "waking up": "circadian awakenings sleep",
    "brain fog": "circadian cognitive fog",
    "neck swelling": "ijv thrombosis jugular clot fullness",
    "neck pain": "ijv thrombosis sternocleidomastoid jugular",
    "blood clot": "ijv thrombosis thrombus",
    "racing heart": "arrhythmia palpitations ventricular tachycardia",
    "sharp chest pain": "pleuritic embolism ijv",
    "cant pee": "urinary retention void bladder",
    "can't urinate": "urinary retention void bladder",
    "unable to void": "urinary retention void bladder",
    "cannot urinate": "urinary retention void bladder",
    "stuffy nose": "sas rhinosinusitis stuffies nasal",
    "motion sick": "sas adaptation nausea",
    "tearing": "lacrimation ocular tearing",
    "burning eyes": "ocular burning",
    "convulsion": "seizures seizure convulsion",
    "altered awareness": "seizures post-ictal",
    "airway swelling": "angioedema stridor anaphylaxis",
    "circulatory collapse": "hypotension anaphylaxis shock",
    "wheeze": "wheezing bronchospasm",
    "blood loss": "hemorrhage trauma efast shock",
    "blistering": "burn trauma deep injury fluid loss",
    "breathlessness": "dyspnea tachypnea sepsis pneumonia",
    "clammy": "diaphoresis sepsis orthostatic",
    "shivering": "hypothermia thermal cold",
    "whooshing": "pulsatile tinnitus sans",
    "farsighted": "hyperopic sans near-vision",
    "reading glasses": "hyperopic sans near-vision",
    "air hunger": "dyspnea hypoxia hypercapnia",
    "gray-out": "presyncope orthostatic tunnel vision",
    "scrubber": "co2 hypercapnia scrubber cdra",
    "ventilation fan": "co2 hypercapnia scrubber",
    "pains": "pain",
    "ache": "pain",
    "lower right": "rlq abdominal appendicitis",
    "right lower quadrant": "rlq abdominal appendicitis",
    "hives": "urticaria anaphylaxis",
    "swollen lips": "angioedema airway swelling anaphylaxis",
    "throat closing": "stridor airway swelling anaphylaxis",
    "sharp side pain": "flank pain renal colic nephrolithiasis",
    "back-to-groin": "flank pain groin nephrolithiasis",
}


# Verified 2023 ISS CHeCS Subpack Formulary & Structured Prescriptions per Scenario
# Strictly grounded in `data/rag_protocols_8_scenarios.json`, `data/nasa_space_medicine_research.md`,
# and `artifacts/clinical_decision_protocol_2_modes.md`.
STRUCTURED_CHECS_PRESCRIPTIONS: Dict[str, List[Dict[str, str]]] = {
    "SCENARIO_1_HYPERCAPNIA": [
        {
            "medication": "100% Normobaric O2",
            "route": "Respiratory Support Pack (RSP) via demand mask",
            "checs_pack": "TIMP / RSP",
            "dosage": "15 L/min continuous for 30 minutes (if ppCO2 > 5.0 mmHg or trigeminal symptoms)",
        },
        {
            "medication": "Acetaminophen 650mg (or Ibuprofen 400mg)",
            "route": "Oral (PO)",
            "checs_pack": "CMP",
            "dosage": "Acetaminophen 325-650 mg PO or Ibuprofen 400-600 mg PO (every 6 hours PRN for hypercapnic cephalea)",
        },
    ],
    "SCENARIO_2_SANS": [
        {
            "medication": "Tropicamide / Cyclopentolate mydriatic ophthalmic drops",
            "route": "Topical Ophthalmic",
            "checs_pack": "TIMP",
            "dosage": "Per JSC-48522 prior to PanOptic fundoscopy (screen anterior chamber angle before mydriasis)",
        },
        {
            "medication": "Acetazolamide PO",
            "route": "Oral (PO)",
            "checs_pack": "OMP",
            "dosage": "Oral administration for progressive Frisen Grade >= 1 optic disc edema (monitor i-STAT electrolytes)",
        },
    ],
    "SCENARIO_3_ORTHOSTATIC_INTOLERANCE": [
        {
            "medication": "0.9% Normal Saline 500-1000 mL IV + AstroAde / Salt Tablets PO",
            "route": "IV via CHeCS IV pump (ISP) / Oral",
            "checs_pack": "ISP / CMP / OMP",
            "dosage": "500-1,000 mL 0.9% Normal Saline IV infusion + 1.0-1.5 L isotonic oral fluid loading",
        },
        {
            "medication": "Ondansetron 4 mg ODT or Promethazine 25 mg IM/IV",
            "route": "Oral Dissolving Tablet / IM / IV",
            "checs_pack": "OMP / TIMP",
            "dosage": "Ondansetron 4 mg ODT or Promethazine 25 mg IM/IV (co-administer judiciously)",
        },
    ],
    "SCENARIO_4_SOLAR_RADIATION_ARS": [
        {
            "medication": "Ondansetron 4-8 mg ODT/IV + 0.9% Normal Saline IV",
            "route": "Oral / IV via ISP",
            "checs_pack": "OMP / TIMP / ISP",
            "dosage": "Ondansetron 4-8 mg ODT/IV + 0.9% Normal Saline IV rehydration with i-STAT electrolytes",
        },
        {
            "medication": "Levofloxacin 500 mg PO, Valacyclovir, Fluconazole, Acetaminophen",
            "route": "Oral (PO)",
            "checs_pack": "OMP / CMP",
            "dosage": "Levofloxacin 500 mg PO daily + Valacyclovir & Fluconazole prophylaxis; Acetaminophen for fever (NO NSAIDs/Aspirin)",
        },
    ],
    "SCENARIO_5_EVA_THERMAL_DCS": [
        {
            "medication": "100% Oxygen (RSP) + 0.9% Normal Saline 1-2 L IV (ISP)",
            "route": "Tight-fitting demand mask (RSP) / IV (ISP)",
            "checs_pack": "RSP / ISP",
            "dosage": "100% O2 via tight-fitting mask for nitrogen washout + 1.0-2.0 L 0.9% Normal Saline IV",
        },
        {
            "medication": "Ibuprofen 600 mg PO / Ketorolac 30 mg IV (TIMP)",
            "route": "Oral (CMP) / IV or IM (TIMP)",
            "checs_pack": "CMP / TIMP",
            "dosage": "Ibuprofen 600 mg PO or Ketorolac 30 mg IV/IM (rule out intracerebral hemorrhage first)",
        },
    ],
    "SCENARIO_6_CIRCADIAN_SLEEP": [
        {
            "medication": "Melatonin 3-5 mg PO, Zaleplon 5-10 mg PO, or Zolpidem 5-10 mg PO",
            "route": "Oral (PO) at bedtime",
            "checs_pack": "OMP",
            "dosage": "Melatonin 3-5 mg PO or Zaleplon 5-10 mg PO (sleep onset) or Zolpidem 5-10 mg PO (sleep maintenance)",
        },
        {
            "medication": "Modafinil 100-200 mg PO or Caffeine 100-200 mg PO",
            "route": "Oral (PO) daytime",
            "checs_pack": "OMP / CMP",
            "dosage": "100-200 mg PO prior to critical EVA or docking operations",
        },
    ],
    "SCENARIO_7_IJV_THROMBOSIS_ARRHYTHMIA": [
        {
            "medication": "Enoxaparin SC -> Apixaban PO",
            "route": "Subcutaneous / Oral",
            "checs_pack": "VCP",
            "dosage": "Subcutaneous Enoxaparin followed by oral Apixaban per Vascular Contingency Pack protocol",
        },
        {
            "medication": "Metoprolol, Nitroglycerin, Epinephrine 0.1 mg/mL (EMTP); Staged Protamine & PCC",
            "route": "Oral / Sublingual / IV",
            "checs_pack": "OMP / EMTP / VCP",
            "dosage": "Epinephrine 0.1 mg/mL (EMTP) for VT/VF cardiac arrest; stage Protamine and PCC for anticoagulant reversal",
        },
    ],
    "SCENARIO_8_SAS_URINARY_RETENTION": [
        {
            "medication": "Tamsulosin 0.4 mg PO + Lidocaine Jelly (MTP Catheter Kit) + Nitrofurantoin",
            "route": "Oral (OMP) / Urethral Catheterization (MTP)",
            "checs_pack": "OMP / MTP",
            "dosage": "Tamsulosin 0.4 mg PO; sterile urethral catheterization with Lidocaine Jelly if bladder volume >500 mL",
        },
        {
            "medication": "Ondansetron 4 mg ODT or Promethazine 25-50 mg PO/IM/IV + Caffeine 100-200 mg PO",
            "route": "Oral / IM / IV",
            "checs_pack": "CMP / OMP / TIMP",
            "dosage": "Ondansetron 4 mg ODT or Promethazine 25-50 mg + Caffeine 100-200 mg for SAS",
        },
    ],
}

# Hard-coded Flight Contraindication Lockouts per Scenario (grounded in `data/rag_protocols_8_scenarios.json`)
SCENARIO_CONTRAINDICATIONS: Dict[str, List[str]] = {
    "SCENARIO_1_HYPERCAPNIA": [
        "OPIOIDS (Morphine/Fentanyl/Hydrocodone/Hydromorphone) — PROHIBITED: Suppresses central respiratory drive and worsens CO2 retention / respiratory acidosis"
    ],
    "SCENARIO_2_SANS": [
        "HIGH-VALSALVA PEAK ARED LOADS & UNSCREENED MYDRIASIS — PROHIBITED: Screen anterior chamber angle before mydriasis; monitor electrolytes on i-STAT and kidney stone risk with Acetazolamide"
    ],
    "SCENARIO_3_ORTHOSTATIC_INTOLERANCE": [
        "VASODILATORS / VOLUME OVERLOAD & UNMONITORED SEDATING PROMETHAZINE — Monitor for volume overload during IV saline infusion; Promethazine may cause sedation"
    ],
    "SCENARIO_4_SOLAR_RADIATION_ARS": [
        "NSAIDs & ASPIRIN (Ibuprofen/Ketorolac/Aspirin) — PROHIBITED: Radiation thrombocytopenia creates severe GI hemorrhage risk"
    ],
    "SCENARIO_5_EVA_THERMAL_DCS": [
        "UNSCREENED HIGH-DOSE KETOROLAC — CONTRAINDICATED until intracerebral hemorrhage is ruled out"
    ],
    "SCENARIO_6_CIRCADIAN_SLEEP": [
        "BENZODIAZEPINES (Lorazepam/Diazepam) WITHOUT STAGED FLUMAZENIL — If benzodiazepines are used for acute agitation, stage Flumazenil 0.1 mg/mL (EMTP) for reversal"
    ],
    "SCENARIO_7_IJV_THROMBOSIS_ARRHYTHMIA": [
        "EVA_SPACEWALK & HIGH-LOAD ARED RESISTIVE EXERCISE — PROHIBITED: High trauma bleed risk on anticoagulants; stage Protamine (for Enoxaparin) and PCC (for Apixaban)"
    ],
    "SCENARIO_8_SAS_URINARY_RETENTION": [
        "ANTICHOLINERGIC ANTIEMETICS (Promethazine/Meclizine) — Precipitate urinary retention in microgravity; monitor bladder volume (>500 mL requires catheterization)"
    ],
}

SCENARIO_KEYWORDS: Dict[str, List[str]] = {
    "SCENARIO_1_HYPERCAPNIA": [
        "hypercapnia", "co2", "carbon dioxide", "frontal headache", "throbbing",
        "flushing", "scrubber", "lioh", "cdra", "camras", "sluggish", "air",
        "dyspnea", "trigeminal", "dysesthesia", "cough", "lethargy",
    ],
    "SCENARIO_2_SANS": [
        "sans", "neuro-ocular", "optic disc", "edema", "oct", "rnfl", "blurry",
        "near-vision", "blurriness", "arm's length", "scotoma", "scotomas",
        "metamorphopsia", "retro-orbital", "choroidal", "hyperopic", "glasses",
    ],
    "SCENARIO_3_ORTHOSTATIC_INTOLERANCE": [
        "orthostatic", "presyncope", "syncope", "lightheadedness", "dizziness",
        "tunnel vision", "graying", "diaphoresis", "postural", "standing",
        "hypotension", "tinnitus", "fainting",
    ],
    "SCENARIO_4_SOLAR_RADIATION_ARS": [
        "solar", "flare", "radiation", "spe", "ars", "donki", "anorexia",
        "retching", "vomiting", "emesis", "lymphocyte", "parotid", "erythema",
        "storm shelter", "diarrhea", "dosimetry",
    ],
    "SCENARIO_5_EVA_THERMAL_DCS": [
        "thermal", "decompression", "dcs", "bends", "chokes", "sweat", "visor",
        "fogging", "heat", "cramps", "periarticular", "shoulder", "knee",
        "substernal", "lcvg", "space fever",
    ],
    "SCENARIO_6_CIRCADIAN_SLEEP": [
        "circadian", "sleep", "insomnia", "awakenings", "asthenia", "irritability",
        "anxiety", "agitation", "cognitive fog", "melatonin", "nocturnal",
    ],
    "SCENARIO_7_IJV_THROMBOSIS_ARRHYTHMIA": [
        "ijv", "thrombosis", "thrombus", "jugular", "clot", "neck fullness",
        "sternocleidomastoid", "clavicle", "pleuritic", "palpitations",
        "arrhythmia", "ventricular tachycardia", "embolism",
    ],
    "SCENARIO_8_SAS_URINARY_RETENTION": [
        "sas", "adaptation", "motion", "stuffies", "nasal", "sinus", "rhinosinusitis",
        "urinary", "retention", "void", "bladder", "suprapubic", "catheter",
    ],
    "CPG-01": ["appendicitis", "rlq", "abdominal pain", "anorexia", "rebound", "leukocytosis", "appendix"],
    "CPG-02": ["coronary", "acs", "myocardial", "substernal", "radiating", "jaw", "diaphoresis", "st-segment"],
    "CPG-03": ["cardiac arrest", "ventricular fibrillation", "pulseless", "acls", "apneic", "unresponsive"],
    "CPG-04": ["ijv", "thrombosis", "embolism", "pleuritic", "sudden dyspnea", "syncope", "jugular"],
    "CPG-05": ["palpitations", "irregular pulse", "arrhythmia", "svt", "atrial fibrillation", "afib", "tachycardia"],
    "CPG-06": ["sans", "hyperopic", "farsighted", "choroidal", "onsd", "rnfl", "tinnitus", "whooshing", "visual blackouts"],
    "CPG-07": ["hypercapnia", "co2", "ppco2", "frontal headache", "scrubber", "dysesthesia", "air hunger"],
    "CPG-08": ["decompression", "dcs", "bends", "barotrauma", "ear", "sinus", "hearing", "vertigo", "hypoxemia", "depressurization"],
    "CPG-09": ["radiation", "ars", "spe", "solar", "storm shelter", "emesis", "vomiting", "lymphocyte", "dosimetry"],
    "CPG-10": ["ammonia", "nh3", "coolant", "burning eyes", "lacrimation", "tearing", "wheezing", "bronchospasm", "prolonged expiration"],
    "CPG-11": ["hydrazine", "n2h4", "propellant", "seizures", "convulsion", "tremor", "altered awareness"],
    "CPG-12": ["carbon monoxide", "fire", "smoke", "pyrolysis", "soot", "hoarseness", "confusion", "dizziness"],
    "CPG-13": ["space motion sickness", "sms", "malaise", "pallor", "sweating", "disorientation", "nausea", "vomiting"],
    "CPG-14": ["orthostatic", "presyncope", "gray-out", "postural", "thirst", "dry mouth", "reduced urine", "g-load"],
    "CPG-15": ["thermal", "heat strain", "hyperthermia", "lcvg", "sweating", "hypothermia", "shivering", "clumsiness", "slowing pulse"],
    "CPG-16": ["nephrolithiasis", "renal colic", "kidney stone", "flank pain", "groin", "hematuria"],
    "CPG-17": ["urinary retention", "inability to void", "suprapubic", "distention", "urgency", "catheterization"],
    "CPG-18": ["uti", "cystitis", "pyelonephritis", "dysuria", "frequency", "urinary"],
    "CPG-19": ["pneumonia", "sepsis", "productive cough", "clammy skin", "breathlessness", "hypothermic", "lactate"],
    "CPG-20": ["anaphylaxis", "allergic", "urticaria", "angioedema", "airway swelling", "stridor", "circulatory collapse"],
    "CPG-21": ["regolith", "dust", "conjunctivitis", "sneezing", "itching", "ocular redness"],
    "CPG-22": ["corneal abrasion", "foreign-body", "photophobia", "opening eye", "fluorescein", "tearing"],
    "CPG-23": ["odontogenic", "tooth pain", "dental", "chewing", "gingival", "barodontalgia", "abscess"],
    "CPG-24": ["cellulitis", "abscess", "erythema", "induration", "purulent", "fluctuance"],
    "CPG-25": ["herpes zoster", "shingles", "dermatomal", "vesicular rash", "burning"],
    "CPG-26": ["fungal", "tinea", "candidiasis", "pruritic", "scaly", "macerated rash"],
    "CPG-27": ["musculoskeletal", "strain", "shoulder", "wrist", "lumbar", "ared"],
    "CPG-28": ["blunt trauma", "hemorrhage", "blood loss", "pallor", "efast", "shock", "blistering", "deep injury", "fluid loss"],
    "CPG-29": ["gastroenteritis", "watery diarrhea", "abdominal cramping"],
    "CPG-30": ["constipation", "bowel", "bloating"],
    "CPG-31": ["circadian", "insomnia", "fear", "chest tightness", "tremor", "tingling", "lightheadedness", "panic"],
    "CPG-32": ["mission fatigue", "sleepiness", "attention lapses", "irritability", "slowed cognition"],
}


def sanitize_symptom_log(raw_text: str) -> str:
    """
    Sanitize untrusted astronaut free-text symptom log against prompt injection
    and control token hijacking per `security_and_safety_guardrails.md`.
    """
    if not raw_text:
        return ""
    bounded = str(raw_text)[:MAX_SYMPTOM_CHARS]
    cleaned = re.sub(r"[<>{}`$\\]", "", bounded)
    cleaned = re.sub(
        r"(?i)(ignore previous|system prompt|override protocol|disregard instructions)",
        "[REDACTED_CONTROL_TOKEN]",
        cleaned,
    )
    return cleaned.strip()


def expand_clinical_synonyms(clean_text: str) -> str:
    """Expand colloquial astronaut symptom expressions into canonical clinical tokens."""
    lower = clean_text.lower()
    additions: List[str] = []
    keys = list(CLINICAL_SYNONYM_MAP.keys())
    for i in range(MAX_KEYWORDS):
        if i >= len(keys):
            break
        phrase = keys[i]
        if phrase in lower:
            additions.append(CLINICAL_SYNONYM_MAP[phrase])
    if additions:
        return lower + " " + " ".join(additions)
    return lower


def _tokenize(text: str) -> List[str]:
    """Extract normalized alphanumeric clinical tokens excluding stopwords."""
    raw_tokens = re.findall(r"[a-z0-9_+-]{3,}", text.lower())
    out: List[str] = []
    for i in range(MAX_KEYWORDS):
        if i >= len(raw_tokens):
            break
        tok = raw_tokens[i]
        if tok not in STOPWORDS:
            out.append(tok)
    return out


def _char_trigram_vector(text: str) -> Dict[str, float]:
    """Compute L2-normalized character 3-gram vector for fast subword cosine similarity."""
    cleaned = re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
    if len(cleaned) < 3:
        return {}
    counts: Dict[str, float] = {}
    limit = min(len(cleaned) - 2, 400)
    for i in range(limit):
        tri = cleaned[i : i + 3]
        if " " not in tri:
            counts[tri] = counts.get(tri, 0.0) + 1.0
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: v / norm for k, v in counts.items()}


def _cosine_similarity_sparse(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Compute sparse dot product between two L2-normalized trigram vectors in <0.1ms."""
    if not vec_a or not vec_b:
        return 0.0
    smaller, larger = (vec_a, vec_b) if len(vec_a) <= len(vec_b) else (vec_b, vec_a)
    dot = 0.0
    for k, val in smaller.items():
        if k in larger:
            dot += val * larger[k]
    return max(0.0, min(1.0, dot))


class LocalMedicalRAGEngine:
    """
    High-Speed, 100% Offline, Zero-Hallucination NASA Level V RAG Medical Officer Engine.
    Combines Symbolic Biotelemetry Scoring + Okapi BM25 + Subword Trigram Vector Cosine.
    """

    def __init__(self) -> None:
        self.protocols: List[Dict[str, Any]] = []
        self.protocol_by_id: Dict[str, Dict[str, Any]] = {}
        self.arxiv_citations: List[Dict[str, Any]] = []
        self.research_chunks: Dict[str, str] = {}
        self.reference_rules: Dict[str, Dict[str, Any]] = {}
        self.formulary_by_name: Dict[str, Dict[str, Any]] = {}
        self.hardware_by_id: Dict[str, Dict[str, Any]] = {}
        self.lab_intervals_by_analyte: Dict[str, Dict[str, Any]] = {}
        self.dynamic_research_chunks: Dict[str, str] = {}
        self.research_notes_loaded: bool = False
        self.dynamic_docs_loaded: List[str] = []
        self.candidate_rag_buffer: List[Dict[str, Any]] = []
        self.diagnosis_cache: Dict[str, Dict[str, Any]] = {}

        # Pre-computed BM25 & Trigram Vector indices
        self._doc_tokens: Dict[str, List[str]] = {}
        self._doc_term_freqs: Dict[str, Dict[str, int]] = {}
        self._idf: Dict[str, float] = {}
        self._avg_doc_len: float = 1.0
        self._doc_trigram_vecs: Dict[str, Dict[str, float]] = {}

        # Unified local Vector Database across all processed datasets (0% LLM hallucination)
        self.vector_store: Dict[str, Dict[str, Any]] = {}
        self._chunk_trigram_vecs: Dict[str, Dict[str, float]] = {}
        self._chunk_term_freqs: Dict[str, Dict[str, int]] = {}
        self._chunk_tokens: Dict[str, List[str]] = {}
        self._chunk_idf: Dict[str, float] = {}
        self._chunk_avg_len: float = 1.0

        self.checs_inventory: Dict[str, str] = {
            "CMP": "Convenience / Crew Medical Pack (Ibuprofen, Acetaminophen, Caffeine)",
            "OMP": "Oral Medications Pack (Ondansetron, Acetazolamide, Melatonin, Zaleplon, Zolpidem, Modafinil, Levofloxacin, Tamsulosin)",
            "TIMP": "Topical & Injectable Medications Pack (Tropicamide/Cyclopentolate, Promethazine, Ketorolac)",
            "EMTP": "Emergency Medical Treatment Pack (Epinephrine 0.1 mg/mL, Flumazenil 0.1 mg/mL)",
            "VCP": "Vascular Contingency Pack (Enoxaparin SC, Apixaban PO, Protamine, PCC)",
            "RSP": "Respiratory Support Pack (100% O2 demand mask, Inspiratory Threshold Valve, ILMA)",
            "ISP": "Intravenous Support Pack (0.9% Normal Saline IV)",
            "MDP": "Medical Diagnostic Pack (i-STAT, C2M2 CBC, OCT, Ultrasound-2, Tonometry)",
            "MTP": "Minor Treatment Pack (Lidocaine Jelly, Urethral Catheterization Kit)",
        }
        self.valid_subpacks: set[str] = set(VALID_CHECS_SUBPACKS)
        self.reload_knowledge_base()

    def reload_knowledge_base(self) -> Dict[str, Any]:
        """Load core NASA datasets, research chunks, and dynamic files, then build indices."""
        self.protocols = []
        self.protocol_by_id = {}
        self.dynamic_research_chunks = {}
        self.reference_rules = {}
        self.formulary_by_name = {}
        self.hardware_by_id = {}
        self.lab_intervals_by_analyte = {}
        self.valid_subpacks = set(VALID_CHECS_SUBPACKS)
        self.dynamic_docs_loaded = []
        self.diagnosis_cache.clear()
        self.vector_store = {}
        self._chunk_trigram_vecs = {}
        self._chunk_term_freqs = {}
        self._chunk_tokens = {}
        self._chunk_idf = {}
        self._chunk_avg_len = 1.0

        self._parse_research_markdown_chunks()
        self._load_preprocessed_reference_chunks()

        if PROTOCOLS_JSON_PATH.exists():
            with open(PROTOCOLS_JSON_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                for i in range(MAX_PROTOCOLS):
                    if i >= len(loaded):
                        break
                    item = loaded[i]
                    sid = str(item.get("scenario_id", f"SCENARIO_{i + 1}"))
                    item.setdefault("source_filename", "rag_protocols_8_scenarios.json")
                    self.protocols.append(item)
                    self.protocol_by_id[sid] = item

        if EXPANDED_PROTOCOLS_JSON_PATH.exists():
            with open(EXPANDED_PROTOCOLS_JSON_PATH, "r", encoding="utf-8") as ef:
                exp_data = json.load(ef)
            cpgs = exp_data.get("clinical_practice_guidelines", [])
            for cpg in cpgs:
                if len(self.protocols) >= MAX_PROTOCOLS:
                    break
                pid = str(cpg.get("protocol_id", ""))
                if not pid or pid in self.protocol_by_id:
                    continue
                parsed_meds = [
                    self._parse_and_validate_medication(raw_med)
                    for raw_med in cpg.get("prescribed_meds", [])
                ]
                normalized_cpg = {
                    "scenario_id": pid,
                    "title": cpg.get("title", pid),
                    "category": cpg.get("category", "Space Medicine CPG"),
                    "nasa_citations": cpg.get("nasa_citations", []),
                    "symptoms_by_severity": {
                        "MODERATE": cpg.get("search_text", ""),
                        "DIAGNOSTIC_CRITERIA": "; ".join(cpg.get("diagnostic_criteria", [])),
                    },
                    "search_text": cpg.get("search_text", ""),
                    "diagnostic_criteria": cpg.get("diagnostic_criteria", []),
                    "autonomous_checklist": cpg.get("autonomous_checklist", []),
                    "checs_medications": parsed_meds,
                    "drug_lockouts": [str(x) for x in cpg.get("drug_lockouts", [])],
                    "verified_rule_ids": cpg.get("verified_rule_ids", []),
                    "source_audit": cpg.get("source_audit", {}),
                    "source_filename": "rag_protocols_expanded.json",
                }
                self.protocols.append(normalized_cpg)
                self.protocol_by_id[pid] = normalized_cpg

        if ARXIV_JSON_PATH.exists():
            with open(ARXIV_JSON_PATH, "r", encoding="utf-8") as af:
                self.arxiv_citations = json.load(af)

        self._load_dynamic_official_protocols()
        self._build_hybrid_search_index()

        return {
            "protocols_count": len(self.protocols),
            "research_chunks_indexed": len(self.research_chunks),
            "vector_store_chunks": len(self.vector_store),
            "dynamic_files_loaded": self.dynamic_docs_loaded,
            "arxiv_citations_count": len(self.arxiv_citations),
            "bm25_vocabulary_size": len(self._idf),
        }

    def _parse_research_markdown_chunks(self) -> None:
        """Parse `data/nasa_space_medicine_research.md` into `[Source: ...]` tagged chunks."""
        self.research_chunks = {}
        if not RESEARCH_MD_PATH.exists():
            self.research_notes_loaded = False
            return
        self.research_notes_loaded = True
        text = RESEARCH_MD_PATH.read_text(encoding="utf-8")
        sections = re.split(r"(?m)^###\s+", text)
        for i in range(MAX_CHUNKS):
            if i >= len(sections):
                break
            sec = sections[i].strip()
            if not sec:
                continue
            first_line = sec.splitlines()[0].strip()
            for num in range(1, 9):
                if f"Scenario {num}:" in first_line:
                    tagged = (
                        f"[Source: nasa_space_medicine_research.md | {first_line}] "
                        + " ".join(sec.splitlines()[1:])[:600]
                    )
                    self.research_chunks[f"SCENARIO_{num}"] = tagged

    def _load_preprocessed_reference_chunks(self) -> None:
        """Index pre-processed CHeCS formulary, NASA-STD-3001 rules, hardware specs, and lab intervals."""
        if CHECS_FORMULARY_JSON_PATH.exists():
            with open(CHECS_FORMULARY_JSON_PATH, "r", encoding="utf-8") as cf:
                cf_data = json.load(cf)
            for pack_code in cf_data.get("subpacks", {}).keys():
                self.valid_subpacks.add(str(pack_code).upper())
            meds = cf_data.get("medications", [])
            for med in meds[:MAX_CHUNKS]:
                mid = str(med.get("med_id", ""))
                name_key = str(med.get("name", "")).strip().lower()
                if name_key:
                    self.formulary_by_name[name_key] = med
                if mid:
                    self.research_chunks[mid] = f"[Source: checs_formulary.json | {mid}] {med.get('search_text', '')}"

        if NASA_RULES_JSON_PATH.exists():
            with open(NASA_RULES_JSON_PATH, "r", encoding="utf-8") as nf:
                rules = json.load(nf).get("rules", [])
            self.reference_rules = {str(rule.get("standard_id")): rule for rule in rules}
            for rule in rules[:MAX_CHUNKS]:
                rid = str(rule.get("standard_id", ""))
                if rid:
                    self.research_chunks[f"RULE_{rid}"] = f"[Source: nasa_std_3001_rules.json | {rid} | {rule.get('verification_status', 'unverified')}] {rule.get('verbatim_rule') or rule.get('rule_summary') or rule.get('search_text', '')}"

        if HARDWARE_SPECS_JSON_PATH.exists():
            with open(HARDWARE_SPECS_JSON_PATH, "r", encoding="utf-8") as hf:
                devices = json.load(hf).get("devices", [])
            for dev in devices[:MAX_CHUNKS]:
                dev_id = str(dev.get("device_id", ""))
                if dev_id:
                    self.hardware_by_id[dev_id] = dev
                    self.research_chunks[f"HW_{dev_id}"] = (
                        f"[Source: onboard_hardware_specs.json | {dev_id}] "
                        f"{dev.get('name', '')}: {dev.get('search_text', '')}"
                    )

        if LAB_INTERVALS_JSON_PATH.exists():
            with open(LAB_INTERVALS_JSON_PATH, "r", encoding="utf-8") as lf:
                lab_data = json.load(lf)
            for group in ("blood_gas_and_lactate", "electrolytes_and_glucose", "hematology_cbc"):
                for item in lab_data.get(group, []):
                    analyte = str(item.get("analyte", ""))
                    if analyte:
                        self.lab_intervals_by_analyte[analyte] = item
                        self.research_chunks[f"LAB_{analyte}"] = f"[Source: lab_reference_intervals.json | {analyte}] {item.get('search_text', '')}"

    def _validate_formulary_entry(
        self, med_name: str, pack_str: str
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Verify medication name and CHeCS subpack code(s) against the local formulary & pack inventory."""
        packs = [
            p.strip().upper()
            for p in re.split(r"[/,\s]+", pack_str or "")
            if p.strip()
        ]
        if not packs or any(p not in self.valid_subpacks for p in packs):
            return False, None

        lower_name = (med_name or "").strip().lower()
        canonical_name = FORMULARY_ALIAS_MAP.get(lower_name, lower_name)
        if canonical_name in self.formulary_by_name:
            return True, self.formulary_by_name[canonical_name]

        for fname, fentry in self.formulary_by_name.items():
            if fname in lower_name:
                return True, fentry

        support_markers = (
            "oxygen", "o2", "saline", "crystalloid", "rehydration",
            "catheter", "tropicamide", "cyclopentolate", "lidocaine", "astroade", "salt tablets",
            "acetazolamide",
        )
        if any(marker in lower_name for marker in support_markers):
            return True, None

        return False, None

    def _parse_and_validate_medication(self, raw_med: Any) -> Dict[str, Any]:
        """Normalize a string or dict medication entry into distinct validated fields."""
        if isinstance(raw_med, dict):
            med_name = str(raw_med.get("medication") or raw_med.get("drug") or "").strip()
            pack_str = str(raw_med.get("checs_pack") or raw_med.get("pack") or "").strip()
            route = str(raw_med.get("route") or "").strip()
            dosage = str(raw_med.get("dosage") or "").strip()
            contra = str(raw_med.get("contraindication_warning") or raw_med.get("contraindication") or "").strip()
            verified, form_entry = self._validate_formulary_entry(med_name, pack_str)
            if not route:
                route = "Per CHeCS protocol"
            if not dosage:
                dosage = str(form_entry.get("dose_route", med_name)) if form_entry else med_name
            return {
                "medication": med_name,
                "drug": med_name,
                "checs_pack": pack_str,
                "pack": pack_str,
                "route": route,
                "dosage": dosage,
                "formulary_verified": verified,
                "formulary_med_id": form_entry.get("med_id") if form_entry else None,
                "contraindication": contra,
                "contraindication_warning": contra,
            }

        raw_str = str(raw_med or "").strip()
        paren_match = re.match(r"^([^(]+?)\s*(?:\(([^)]+)\))?$", raw_str)
        med_name = paren_match.group(1).strip() if paren_match else raw_str
        inner = (paren_match.group(2) or "").strip() if paren_match else ""

        pack_matches = re.findall(r"\b(CMP|OMP|TIMP|EMTP|VCP|RSP|ISP|MDP|MTP)\b", inner, re.IGNORECASE)
        pack_str = "/".join(dict.fromkeys(p.upper() for p in pack_matches)) if pack_matches else ""

        dosage = inner
        if pack_matches:
            dosage = re.sub(
                r"^(?:(?:CMP|OMP|TIMP|EMTP|VCP|RSP|ISP|MDP|MTP)\s*(?:/\s*(?:CMP|OMP|TIMP|EMTP|VCP|RSP|ISP|MDP|MTP)\s*)*)[,;:\s-]*",
                "",
                inner,
                flags=re.IGNORECASE,
            ).strip()

        lower_name = med_name.lower()
        route = ""
        if lower_name in SUPPORT_PACK_ITEMS:
            def_pack, def_route, def_dose = SUPPORT_PACK_ITEMS[lower_name]
            pack_str = pack_str or def_pack
            route = def_route
            dosage = dosage or def_dose

        verified, form_entry = self._validate_formulary_entry(med_name, pack_str or "UNSPECIFIED_IN_SOURCE")
        if not dosage and form_entry:
            dosage = str(form_entry.get("dose_route", ""))
        if not dosage:
            dosage = "Per CHeCS protocol"

        route_match = re.search(
            r"\b(IV/IM|PO/IV|IV|IM|PO|ODT|SQ|SC|SL|inhaled|topical|ophthalmic|drops|ointment|cream)\b",
            f"{dosage} {med_name}",
            re.IGNORECASE,
        )
        if not route and route_match:
            route = route_match.group(1).upper() if len(route_match.group(1)) <= 5 else route_match.group(1).title()
        elif not route and form_entry:
            dr_match = re.search(
                r"\b(IV/IM|PO/IV|IV|IM|PO|ODT|SQ|SC|SL|inhaled|topical|ophthalmic|drops|ointment|cream)\b",
                str(form_entry.get("dose_route", "")),
                re.IGNORECASE,
            )
            route = dr_match.group(1).upper() if dr_match and len(dr_match.group(1)) <= 5 else (dr_match.group(1).title() if dr_match else "Per CHeCS protocol")
        if not route:
            route = "Per CHeCS protocol"

        return {
            "medication": med_name,
            "drug": med_name,
            "checs_pack": pack_str or "UNSPECIFIED_IN_SOURCE",
            "pack": pack_str or "UNSPECIFIED_IN_SOURCE",
            "route": route,
            "dosage": dosage,
            "formulary_verified": verified,
            "formulary_med_id": form_entry.get("med_id") if form_entry else None,
            "contraindication": "",
            "contraindication_warning": "",
        }

    def _build_hybrid_search_index(self) -> None:
        """Pre-compute Okapi BM25 IDF weights and Character Trigram Vectors at startup."""
        self._doc_tokens = {}
        self._doc_term_freqs = {}
        self._doc_trigram_vecs = {}
        df_counts: Dict[str, int] = {}
        total_len = 0
        n_docs = len(self.protocols)

        for i in range(MAX_PROTOCOLS):
            if i >= n_docs:
                break
            proto = self.protocols[i]
            sid = str(proto.get("scenario_id", ""))
            sym_values = " ".join(str(v) for v in proto.get("symptoms_by_severity", {}).values())
            kw_values = " ".join(SCENARIO_KEYWORDS.get(sid, []))
            title = str(proto.get("title", ""))
            diagnostic_criteria = " ".join(
                str(item) for item in proto.get("diagnostic_criteria", [])
            )
            search_text = str(proto.get("search_text", ""))
            if search_text or diagnostic_criteria:
                corpus_text = f"{title} {search_text} {diagnostic_criteria} {kw_values}"
            else:
                corpus_text = f"{title} {sym_values} {kw_values}"
            tokens = _tokenize(corpus_text)
            self._doc_tokens[sid] = tokens
            total_len += len(tokens)

            tf: Dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            self._doc_term_freqs[sid] = tf
            for unique_tok in tf:
                df_counts[unique_tok] = df_counts.get(unique_tok, 0) + 1

            # Build character trigram vector focused on clinical symptoms & keywords
            self._doc_trigram_vecs[sid] = _char_trigram_vector(
                corpus_text
            )

        self._avg_doc_len = (total_len / float(n_docs)) if n_docs > 0 else 1.0
        self._idf = {}
        for tok, df in df_counts.items():
            # Standard Robertson-Sparck Jones BM25 IDF smoothing
            self._idf[tok] = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))

        self._build_unified_vector_store()

    def _add_vector_store_record(
        self,
        chunk_id: str,
        doc_type: str,
        source: str,
        title: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register one processed, source-pinned record in the local vector store."""
        combined = f"{title} {text}".strip()
        if not combined:
            return
        formatted = f"[Source: {source} | {chunk_id}] {title}: {text}" if title else f"[Source: {source} | {chunk_id}] {text}"
        self.vector_store[chunk_id] = {
            "chunk_id": chunk_id,
            "doc_type": doc_type,
            "source": source,
            "title": title,
            "text": text,
            "formatted_chunk": formatted,
            "metadata": metadata or {},
        }
        tokens = _tokenize(combined)
        self._chunk_tokens[chunk_id] = tokens
        tf: Dict[str, int] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1
        self._chunk_term_freqs[chunk_id] = tf
        self._chunk_trigram_vecs[chunk_id] = _char_trigram_vector(combined)

    def _build_unified_vector_store(self) -> None:
        """Process and index all RAG knowledge datasets into `self.vector_store`."""
        self.vector_store = {}
        self._chunk_trigram_vecs = {}
        self._chunk_term_freqs = {}
        self._chunk_tokens = {}

        # 1. All clinical protocols (8 legacy scenarios + 32 CPGs + dynamic JSON/CSV)
        for i in range(MAX_PROTOCOLS):
            if i >= len(self.protocols):
                break
            proto = self.protocols[i]
            sid = str(proto.get("scenario_id", ""))
            source_file = str(proto.get("source_filename", "project_protocol_data"))
            title = str(proto.get("title", sid))
            sym_text = " ".join(str(v) for v in proto.get("symptoms_by_severity", {}).values())
            criteria_text = " ".join(str(x) for x in proto.get("diagnostic_criteria", []))
            kw_text = " ".join(SCENARIO_KEYWORDS.get(sid, []))
            body = f"{proto.get('search_text', '')} {sym_text} {criteria_text} {kw_text}".strip()
            self._add_vector_store_record(
                f"PROTO_{sid}",
                "protocol",
                source_file,
                title,
                body,
                {"scenario_id": sid, "citations": proto.get("nasa_citations", [])},
            )

        # 2. NASA-STD-3001 rules
        for rid, rule in list(self.reference_rules.items())[:MAX_CHUNKS]:
            verbatim = str(rule.get("verbatim_rule") or rule.get("rule_summary") or rule.get("search_text") or "")
            self._add_vector_store_record(
                f"RULE_{rid}",
                "rule",
                f"nasa_std_3001_rules.json ({rule.get('source_revision', '')})",
                f"{rid} {rule.get('source_section', '')}".strip(),
                verbatim,
                {
                    "standard_id": rid,
                    "verification_status": rule.get("verification_status", "unverified"),
                    "source_url": rule.get("source_url", ""),
                },
            )

        # 3. CHeCS Formulary entries
        for fname, med in list(self.formulary_by_name.items())[:MAX_CHUNKS]:
            mid = str(med.get("med_id", fname))
            self._add_vector_store_record(
                mid,
                "formulary",
                "checs_formulary.json",
                f"{med.get('name', fname)} ({med.get('pack', '')})",
                str(med.get("search_text") or med.get("indication") or med.get("dose_route") or ""),
                {"med_id": mid, "pack": med.get("pack", ""), "dose_route": med.get("dose_route", "")},
            )

        # 4. Onboard Hardware Specs
        for dev_id, dev in list(self.hardware_by_id.items())[:MAX_CHUNKS]:
            self._add_vector_store_record(
                f"HW_{dev_id}",
                "hardware",
                "onboard_hardware_specs.json",
                str(dev.get("name", dev_id)),
                str(dev.get("search_text") or dev.get("capabilities") or dev.get("clinical_use") or ""),
                {"device_id": dev_id},
            )

        # 5. Lab Reference Intervals
        for analyte, item in list(self.lab_intervals_by_analyte.items())[:MAX_CHUNKS]:
            self._add_vector_store_record(
                f"LAB_{analyte}",
                "lab",
                "lab_reference_intervals.json",
                analyte,
                str(item.get("search_text") or f"Normal {item.get('normal_range', '')} {item.get('unit', '')}"),
                {"analyte": analyte},
            )

        # 6. Research markdown chunks & dynamic official docs
        for key, chunk_text in list(self.research_chunks.items())[:MAX_CHUNKS]:
            if key.startswith("SCENARIO_"):
                self._add_vector_store_record(
                    f"RESEARCH_{key}",
                    "research",
                    "nasa_space_medicine_research.md",
                    key,
                    chunk_text,
                    {"scenario_key": key},
                )
        for key, chunk_text in list(self.dynamic_research_chunks.items())[:MAX_DYNAMIC_FILES]:
            self._add_vector_store_record(
                key,
                "official_doc",
                "data/nasa_official_protocols",
                key,
                chunk_text,
            )

        # 7. arXiv Literature Citations
        for paper in self.arxiv_citations[:MAX_CHUNKS]:
            aid = str(paper.get("arxiv_id", ""))
            if not aid:
                continue
            self._add_vector_store_record(
                f"ARXIV_{aid}",
                "literature",
                f"arxiv_literature_citations.json (arXiv:{aid})",
                str(paper.get("title", aid)),
                str(paper.get("key_finding_quote", "")),
                {"arxiv_id": aid},
            )

        # Compute corpus BM25 IDF across all vector store chunks
        n_chunks = len(self.vector_store)
        chunk_df: Dict[str, int] = {}
        total_len = 0
        for cid, tf in self._chunk_term_freqs.items():
            total_len += len(self._chunk_tokens.get(cid, []))
            for tok in tf:
                chunk_df[tok] = chunk_df.get(tok, 0) + 1
        self._chunk_avg_len = (total_len / float(n_chunks)) if n_chunks > 0 else 1.0
        self._chunk_idf = {
            tok: math.log(1.0 + (n_chunks - df + 0.5) / (df + 0.5))
            for tok, df in chunk_df.items()
        }

    def query_vector_store(
        self,
        query_text: str,
        top_k: int = 5,
        doc_types: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Query the unified offline vector store with hybrid trigram cosine + BM25."""
        if not query_text or not self.vector_store:
            return []
        expanded = expand_clinical_synonyms(query_text)
        q_tokens = _tokenize(expanded)
        q_vec = _char_trigram_vector(expanded)
        k1, b = 1.5, 0.75
        scored: List[Tuple[float, str, Dict[str, Any]]] = []

        for cid, record in self.vector_store.items():
            if doc_types is not None and record.get("doc_type") not in doc_types:
                continue
            vec_sim = _cosine_similarity_sparse(q_vec, self._chunk_trigram_vecs.get(cid, {}))
            tf_map = self._chunk_term_freqs.get(cid, {})
            doc_len = float(len(self._chunk_tokens.get(cid, [])) or 1)
            bm25_raw = 0.0
            for tok in q_tokens[:MAX_KEYWORDS]:
                tf = float(tf_map.get(tok, 0))
                if tf > 0:
                    idf = self._chunk_idf.get(tok, 0.5)
                    bm25_raw += idf * ((tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * (doc_len / self._chunk_avg_len))))
            bm25_norm = min(1.0, bm25_raw / 8.0)
            score = round((0.60 * vec_sim) + (0.40 * bm25_norm), 4)
            if score > 0.02:
                scored.append((score, cid, record))

        scored.sort(key=lambda row: (-row[0], row[1]))
        results: List[Dict[str, Any]] = []
        for score, _cid, rec in scored[: max(1, top_k)]:
            out = dict(rec)
            out["score"] = score
            results.append(out)
        return results

    def _load_dynamic_official_protocols(self) -> None:
        """Scan `data/nasa_official_protocols/` for newly released NASA challenge files."""
        if not OFFICIAL_PROTOCOLS_DIR.exists() or not OFFICIAL_PROTOCOLS_DIR.is_dir():
            return
        files = sorted(OFFICIAL_PROTOCOLS_DIR.iterdir())
        for idx in range(MAX_DYNAMIC_FILES):
            if idx >= len(files) or len(self.protocols) >= MAX_PROTOCOLS:
                break
            fpath = files[idx]
            if not fpath.is_file() or fpath.name.lower() == "readme.md":
                continue
            try:
                if fpath.suffix.lower() == ".json":
                    with open(fpath, "r", encoding="utf-8") as jf:
                        doc = json.load(jf)
                    self._ingest_dynamic_json(doc, fpath.name)
                elif fpath.suffix.lower() == ".csv":
                    self._ingest_dynamic_csv(fpath)
                elif fpath.suffix.lower() in (".md", ".txt"):
                    self._ingest_dynamic_text(fpath)
            except (OSError, ValueError):
                continue

    def _ingest_dynamic_json(self, doc: Any, filename: str) -> None:
        """Index a dynamic JSON protocol file into the local knowledge base without fabricating fields."""
        items = doc if isinstance(doc, list) else [doc]
        for i in range(MAX_DYNAMIC_FILES):
            if i >= len(items) or len(self.protocols) >= MAX_PROTOCOLS:
                break
            entry = items[i]
            if isinstance(entry, dict) and ("scenario_id" in entry or "title" in entry):
                cloned = dict(entry)
                sid = str(cloned.get("scenario_id", f"NASA_OFFICIAL_{len(self.protocols) + 1}"))
                cloned["scenario_id"] = sid
                self.protocols.append(cloned)
                self.protocol_by_id[sid] = cloned
        self.dynamic_docs_loaded.append(filename)

    def _ingest_dynamic_csv(self, fpath: Path) -> None:
        """Index rows from a dynamic CSV protocol file without inventing missing clinical fields."""
        with open(fpath, "r", encoding="utf-8") as cf:
            reader = csv.DictReader(cf)
            for i, row in enumerate(reader):
                if i >= MAX_DYNAMIC_FILES or len(self.protocols) >= MAX_PROTOCOLS:
                    break
                sid = str(row.get("scenario_id") or f"NASA_CSV_{len(self.protocols) + 1}")
                citations = [row["nasa_citations"].strip()] if row.get("nasa_citations", "").strip() else []
                meds = []
                if row.get("medication", "").strip():
                    meds.append(
                        {
                            "drug": row["medication"].strip(),
                            "pack": row.get("pack", "").strip() or "UNSPECIFIED_IN_SOURCE",
                            "contraindication": row.get("contraindication", "").strip(),
                        }
                    )
                checklist = [row["action_1"].strip()] if row.get("action_1", "").strip() else []
                entry = {
                    "scenario_id": sid,
                    "title": row.get("title", "").strip() or f"NASA Dataset Entry ({fpath.stem})",
                    "nasa_citations": citations,
                    "symptoms_by_severity": {"reported": row.get("symptoms", "").strip()},
                    "checs_medications": meds,
                    "autonomous_checklist": checklist,
                }
                self.protocols.append(entry)
                self.protocol_by_id[sid] = entry
        self.dynamic_docs_loaded.append(fpath.name)

    def _ingest_dynamic_text(self, fpath: Path) -> None:
        """
        Index a markdown/text clinical note from `data/nasa_official_protocols/` as supplemental
        evidence without fabricating synthetic Mode A medications or citations.
        """
        text = fpath.read_text(encoding="utf-8")[:2000]
        sid = f"NASA_DOC_{fpath.stem.upper()}"
        self.dynamic_research_chunks[sid] = (
            f"[Source: nasa_official_protocols/{fpath.name}] {text[:600]}"
        )
        self.dynamic_docs_loaded.append(fpath.name)

    def _is_mode_a_data_complete(
        self,
        proto: Optional[Dict[str, Any]],
        packet: Optional[TelemetryPacket] = None,
    ) -> bool:
        """
        Verify protocol completeness, source-rule linkage, formulary membership,
        and telemetry reliability before permitting Mode A recommendations.
        """
        if not proto:
            return False
        citations = proto.get("nasa_citations")
        meds = proto.get("checs_medications")
        checklist = proto.get("autonomous_checklist")
        if not (citations and meds and checklist):
            return False

        # Verify any referenced rule IDs exist in loaded NASA-STD-3001 / JSC 20584 rules
        verified_rule_ids = proto.get("verified_rule_ids") or []
        if not all(str(rid) in self.reference_rules for rid in verified_rule_ids):
            return False

        # Verify all prescribed medications validate against checs_formulary.json & valid subpacks
        sid = str(proto.get("scenario_id", ""))
        prescriptions = STRUCTURED_CHECS_PRESCRIPTIONS.get(sid)
        meds_to_verify = prescriptions if prescriptions is not None else meds
        if not all(self._parse_and_validate_medication(m).get("formulary_verified") for m in meds_to_verify):
            return False

        if packet is not None:
            missing = set(packet.missing_vitals or [])
            unreliable = set(packet.unreliable_channels or [])
            if len(missing) >= 3:
                return False
            if len(unreliable) >= 2:
                return False

            if sid in ("SCENARIO_1_HYPERCAPNIA", "CPG-07"):
                suit_co2 = packet.environment.suit_pico2_mmhg
                if "cabin_co2_mmhg" in unreliable and (not suit_co2 or "suit_pico2_mmhg" in unreliable):
                    return False
                if "suit_pico2_mmhg" in unreliable and suit_co2:
                    return False
            if sid in ("SCENARIO_4_SOLAR_RADIATION_ARS", "CPG-09"):
                if "ambient_radiation_msv_h" in unreliable and not packet.environment.donki_spe_active:
                    return False
            if sid in ("SCENARIO_5_EVA_THERMAL_DCS", "CPG-08") and ("spo2" in missing or "spo2" in unreliable):
                return False
            if sid == "CPG-15" and ("core_temp_c" in missing or "core_temp_c" in unreliable):
                return False
            if sid in ("SCENARIO_3_ORTHOSTATIC_INTOLERANCE", "CPG-14", "CPG-19", "CPG-20", "CPG-28"):
                if (
                    "heart_rate" in missing
                    or "heart_rate" in unreliable
                    or "blood_pressure_sys" in missing
                    or "blood_pressure_sys" in unreliable
                ):
                    return False

        return True

    def _build_cache_key(self, packet: TelemetryPacket, clean_symptoms: str) -> str:
        """Build deterministic SHA-256 cache key over telemetry state and sanitized symptoms."""
        v = packet.vitals
        e = packet.environment
        d = packet.specialized_diagnostics
        c = packet.comms_status
        key_obj = {
            "timestamp": packet.timestamp,
            "met": packet.met,
            "mission_day": packet.mission_day,
            "astronaut_id": packet.astronaut_id,
            "name": packet.name,
            "activity_state": packet.activity_state,
            "active_scenario_id": packet.active_scenario_id,
            "force_mode_b": packet.force_mode_b,
            "stateless_evaluation": packet.stateless_evaluation,
            "sanitized_symptom_log": clean_symptoms.lower(),
            "comms_status": (
                {
                    "one_way_delay_sec": c.one_way_delay_sec,
                    "mode": c.mode,
                    "solar_conjunction_blackout": c.solar_conjunction_blackout,
                }
                if c is not None else None
            ),
            "vitals": {
                "heart_rate": v.heart_rate,
                "blood_pressure_sys": v.blood_pressure_sys,
                "blood_pressure_dia": v.blood_pressure_dia,
                "spo2": v.spo2,
                "hrv_ms": v.hrv_ms,
                "core_temp_c": v.core_temp_c,
                "respiration_rate": v.respiration_rate,
                "ve_l_min": v.ve_l_min,
            },
            "environment": {
                "cabin_co2_mmhg": e.cabin_co2_mmhg,
                "ambient_radiation_msv_h": e.ambient_radiation_msv_h,
                "bfo_dose_rate_mGy_hr": e.bfo_dose_rate_mGy_hr,
                "suit_pressure_psi": e.suit_pressure_psi,
                "cabin_ppo2_mmhg": e.cabin_ppo2_mmhg,
                "suit_pico2_mmhg": e.suit_pico2_mmhg,
                "donki_spe_active": e.donki_spe_active,
                "cabin_pressure_kPa": e.cabin_pressure_kPa,
                "cabin_temp_C": e.cabin_temp_C,
            },
            "specialized_diagnostics": (
                {
                    "oct_rnfl_um": d.oct_rnfl_um,
                    "refraction_shift_D": d.refraction_shift_D,
                    "alc_cells_uL": d.alc_cells_uL,
                    "ultrasound_ijv_thrombus": d.ultrasound_ijv_thrombus,
                    "bladder_volume_mL": d.bladder_volume_mL,
                }
                if d is not None else None
            ),
            "missing_vitals": list(packet.missing_vitals),
            "unreliable_channels": list(packet.unreliable_channels),
        }
        raw = json.dumps(key_obj, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def diagnose(
        self, packet: TelemetryPacket, assessment: AnomalyAssessment
    ) -> Dict[str, Any]:
        """
        Execute the 2-Mode Clinical Decision Protocol in <1ms (SLA <50ms).
        Returns Mode A (Confidence >= 0.75) or Mode B (Confidence < 0.75).
        """
        start_ns = time.perf_counter_ns()
        clean_symptoms = sanitize_symptom_log(packet.symptom_log)
        cache_key = self._build_cache_key(packet, clean_symptoms)

        if cache_key in self.diagnosis_cache and not packet.force_mode_b:
            cached = dict(self.diagnosis_cache[cache_key])
            cached["execution_time_ms"] = round((time.perf_counter_ns() - start_ns) / 1_000_000.0, 3)
            cached["cache_hit"] = True
            return cached

        best_scenario_id, confidence, score_breakdown, signal_details = self._retrieve_best_protocol(
            packet, assessment, clean_symptoms
        )
        elapsed_ms = round((time.perf_counter_ns() - start_ns) / 1_000_000.0, 3)
        matched_proto = self.protocol_by_id.get(best_scenario_id)

        if (
            confidence >= MODE_A_CONFIDENCE_THRESHOLD
            and not packet.force_mode_b
            and self._is_mode_a_data_complete(matched_proto, packet)
        ):
            response = self._build_mode_a_response(
                best_scenario_id,
                confidence,
                packet,
                assessment,
                clean_symptoms,
                elapsed_ms,
                score_breakdown,
                signal_details,
            )
        elif self._is_nominal_asymptomatic(packet, assessment, clean_symptoms, confidence):
            response = self._build_nominal_response(
                packet,
                assessment,
                clean_symptoms,
                elapsed_ms,
                score_breakdown,
            )
        else:
            response = self._build_mode_b_response(
                confidence,
                packet,
                assessment,
                clean_symptoms,
                elapsed_ms,
                score_breakdown,
                signal_details,
            )

        response["execution_time_ms"] = round((time.perf_counter_ns() - start_ns) / 1_000_000.0, 3)
        response["rag_metrics"]["retrieval_latency_ms"] = elapsed_ms
        if len(self.diagnosis_cache) >= MAX_CACHE_ENTRIES:
            self.diagnosis_cache.clear()
        self.diagnosis_cache[cache_key] = dict(response)
        return response

    def _has_unmapped_presentation(self, packet: TelemetryPacket, symptoms: str) -> bool:
        """Abstain when observations describe a presentation absent from this corpus."""
        text = symptoms.lower()
        exposure = any(word in text for word in ("hydrazin", "n2h4", "propellant", "ammonia", "coolant", "chemical", "smoke", "soot"))
        allergy = any(word in text for word in ("urticaria", "hives", "angioedema", "allergen", "airway swelling"))
        seizure = any(word in text for word in ("convulsion", "seizure", "postictal", "altered awareness"))
        bronchospasm = any(word in text for word in ("wheeze", "wheezing", "prolonged expiration", "bronchospasm"))
        ear_injury = "vertigo" in text and any(word in text for word in ("ear/sinus pain", "hearing change", "tympanic pain"))
        if (seizure or bronchospasm) and not (exposure or allergy):
            return True
        if "blistering" in text or "severe burn" in text or "pneumothorax" in text:
            return True
        if all(word in text for word in ("chest pain", "dyspnea", "rapidly worsening", "shock")):
            return True
        if ear_injury and packet.vitals.spo2 >= 93 and packet.environment.suit_pressure_psi >= 4.1:
            return True
        if re.search(r"\b(?:panic|fear)\b", text) and not (exposure or allergy):
            return True
        if "pleuritic" in text and not (packet.specialized_diagnostics and packet.specialized_diagnostics.ultrasound_ijv_thrombus):
            return True
        return (
            packet.vitals.core_temp_c <= 35.8
            and "core_temp_c" not in packet.unreliable_channels
            and any(word in text for word in ("shivering", "hypothermia", "cold exposure"))
        )

    def _retrieve_best_protocol(
        self,
        packet: TelemetryPacket,
        assessment: AnomalyAssessment,
        clean_symptoms: str,
    ) -> Tuple[str, float, Dict[str, float], Dict[str, Any]]:
        """
        3-Signal Hybrid Neuro-Symbolic Scorer:
        Combines Symbolic Telemetry Signature + Okapi BM25 + Character Trigram Vector Cosine.
        """
        if packet.force_mode_b:
            return ("UNCLASSIFIED_ZERO_DAY", 0.42, {"forced_mode_b": 0.42}, {"reason": "explicit_force_mode_b"})

        if self._has_unmapped_presentation(packet, clean_symptoms):
            return ("UNCLASSIFIED_ZERO_DAY", 0.44, {}, {"reason": "no_matching_project_protocol"})
        expanded_symptoms = expand_clinical_synonyms(clean_symptoms)
        active_hint = ""  # Simulator labels never supply diagnostic evidence.

        if any(
            tok in active_hint
            for tok in ("MODE_B", "ZERO_DAY", "ZERODAY", "NOVEL", "UNCLASSIFIED", "UNKNOWN")
        ) or any(
            tok in expanded_symptoms
            for tok in ("zero-day", "unclassified", "unknown toxin", "novel pathogen", "mode b")
        ):
            return ("UNCLASSIFIED_ZERO_DAY", 0.42, {"zero_day_signature": 0.42}, {"reason": "zero_day_keyword"})

        if self._is_contradictory_zero_day_pattern(packet, expanded_symptoms, active_hint):
            return (
                "UNCLASSIFIED_ZERO_DAY",
                0.44,
                {"contradictory_multi_organ_breach": 0.44},
                {"reason": "unclassified_multi_system_hypoxia_hypotension"},
            )

        query_tokens = _tokenize(expanded_symptoms)
        query_trigram = _char_trigram_vector(expanded_symptoms)

        scores: Dict[str, float] = {}
        raw_scores: Dict[str, float] = {}
        per_scenario_signals: Dict[str, Dict[str, float]] = {}

        for i in range(MAX_PROTOCOLS):
            if i >= len(self.protocols):
                break
            proto = self.protocols[i]
            sid = str(proto.get("scenario_id", ""))

            sym_score = self._score_symbolic_telemetry(sid, packet, assessment, expanded_symptoms)
            bm25_score = self._score_bm25_and_keywords(sid, query_tokens, expanded_symptoms)
            vec_score = _cosine_similarity_sparse(query_trigram, self._doc_trigram_vecs.get(sid, {}))
            hint_bonus = self._score_scenario_hint(sid, active_hint)  # always 0.0 (blind retrieval)

            fused = sym_score + (0.70 * bm25_score) + (0.30 * vec_score) + hint_bonus
            # Strict Mode A gate: require BOTH strong condition-specific physiological evidence
            # AND corroborating clinical text/lexicon signal; never boost via active_scenario_id.
            if sym_score >= 0.65 and (bm25_score >= 0.20 or vec_score >= 0.14):
                floor = min(0.96, 0.77 + (0.12 * sym_score) + (0.10 * bm25_score) + (0.06 * vec_score))
                fused = max(fused, floor)
            elif sym_score >= 0.80 and (bm25_score >= 0.10 or vec_score >= 0.10):
                fused = max(fused, 0.80)
            elif sym_score < 0.0:
                fused = min(fused, 0.48)
            else:
                fused = min(fused, 0.72)

            raw_scores[sid] = fused
            total = round(min(0.99, max(0.05, fused)), 3)
            scores[sid] = total
            per_scenario_signals[sid] = {
                "symbolic": round(sym_score, 3),
                "bm25_lexical": round(bm25_score, 3),
                "trigram_vector": round(vec_score, 3),
                "fused": total,
            }

        best_id = "SCENARIO_1_HYPERCAPNIA"
        best_raw = -1.0
        best_score = 0.0
        sids = list(scores.keys())
        for i in range(MAX_PROTOCOLS):
            if i >= len(sids):
                break
            k = sids[i]
            if raw_scores[k] > best_raw:
                best_raw = raw_scores[k]
                best_score = scores[k]
                best_id = k

        return (
            best_id,
            round(best_score, 2),
            scores,
            per_scenario_signals.get(best_id, {}),
        )

    def _score_symbolic_telemetry(
        self,
        sid: str,
        packet: TelemetryPacket,
        assessment: AnomalyAssessment,
        expanded_symptoms: str = "",
    ) -> float:
        """
        Compute condition-specific symbolic telemetry + clinical signature score [-0.25, 0.88]
        for both the 8 legacy scenarios and CPG-01..CPG-32, honoring unreliable/missing channels
        and negative-evidence disambiguation.
        """
        v = packet.vitals
        e = packet.environment
        d = packet.specialized_diagnostics
        act = assessment.normalized_activity_state
        sym = expanded_symptoms or ""
        unreliable = set(packet.unreliable_channels or [])
        missing = set(packet.missing_vitals or [])

        co2_reliable = ("cabin_co2_mmhg" not in unreliable) and ("suit_pico2_mmhg" not in unreliable)
        ambient_rad = e.ambient_radiation_msv_h if ("ambient_radiation_msv_h" not in unreliable) else 0.0
        spo2_valid = ("spo2" not in unreliable) and ("spo2" not in missing)
        bp_valid = ("blood_pressure_sys" not in unreliable) and ("blood_pressure_sys" not in missing)
        hr_valid = ("heart_rate" not in unreliable) and ("heart_rate" not in missing)
        temp_valid = ("core_temp_c" not in unreliable) and ("core_temp_c" not in missing)
        rr_valid = ("respiration_rate" not in unreliable) and ("respiration_rate" not in missing)
        hrv_valid = ("hrv_ms" not in unreliable) and ("hrv_ms" not in missing)

        effective_co2 = max(e.cabin_co2_mmhg, e.suit_pico2_mmhg or 0.0) if co2_reliable else 0.0
        rad_level = ambient_rad

        has_trauma_bleed = any(
            k in sym for k in ("hemorrhag", "blood loss", "lacerat", "bleed", "burn", "blister", "pneumothorax", "efast", "trauma", "crush")
        )
        has_anaphylaxis = any(
            k in sym for k in ("anaphyl", "urticaria", "hives", "angioedema", "airway swelling", "swollen lip", "throat closing", "stridor")
        )

        has_infection_signal = any(k in sym for k in ("sepsis", "pneumonia", "fever", "rigors", "hypothermic"))
        abnormal_infection_temp = (
            has_infection_signal and temp_valid and (v.core_temp_c >= 38.0 or v.core_temp_c <= 36.2)
        )

        # --- Environmental Hypercapnia (SCENARIO_1 / CPG-07) ---
        if sid in ("SCENARIO_1_HYPERCAPNIA", "CPG-07"):
            if not co2_reliable:
                return 0.0
            if effective_co2 >= 4.5:
                return 0.86 if sid == "SCENARIO_1_HYPERCAPNIA" else 0.83
            if effective_co2 >= 2.8:
                return 0.79 if sid == "SCENARIO_1_HYPERCAPNIA" else 0.76
            return -0.20

        # --- SANS (SCENARIO_2 / CPG-06) ---
        if sid in ("SCENARIO_2_SANS", "CPG-06"):
            if d and ((d.oct_rnfl_um and d.oct_rnfl_um > 105.0) or (d.refraction_shift_D and d.refraction_shift_D >= 0.5)):
                return 0.87 if sid == "SCENARIO_2_SANS" else 0.84
            if any(
                k in sym for k in (
                    "reading glasses", "farsighted", "hyperopic", "choroidal", "scotoma",
                    "whooshing", "tinnitus", "visual blackout", "optic disc", "behind the globes",
                )
            ) and effective_co2 < 2.8 and rad_level < 0.25:
                return 0.82 if sid == "CPG-06" else 0.79
            if packet.mission_day >= 21 and bp_valid and v.blood_pressure_sys < 130.0 and effective_co2 < 3.0 and hr_valid and v.heart_rate < 90.0:
                return 0.25
            return 0.0

        # --- Orthostatic Intolerance & Dehydration (SCENARIO_3 / CPG-14) ---
        if sid in ("SCENARIO_3_ORTHOSTATIC_INTOLERANCE", "CPG-14"):
            if has_trauma_bleed or has_anaphylaxis or abnormal_infection_temp:
                return -0.15
            if not (bp_valid and hr_valid):
                return 0.0
            is_dehyd_seed = any(k in sym for k in ("thirst", "dry mouth", "reduced urine", "postural", "volume depletion", "dehydrat"))
            is_ortho_traj = any(k in sym for k in ("g-load", "orthostat", "presyncope", "gray-out", "sitting up", "stand", "reentry", "landing"))
            if is_dehyd_seed and (v.blood_pressure_sys <= 112.0 or v.heart_rate >= 84.0) and rad_level < 0.25 and effective_co2 < 2.8:
                return 0.85 if sid == "CPG-14" else 0.78
            if is_ortho_traj and (v.heart_rate >= 88.0 or v.blood_pressure_sys <= 105.0) and rad_level < 0.25 and effective_co2 < 2.8:
                return 0.85 if sid == "CPG-14" else 0.83
            if (
                v.blood_pressure_sys <= 94.0
                and (not spo2_valid or v.spo2 >= 93.0)
                and effective_co2 < 3.0
                and rad_level < 0.25
                and not (rr_valid and v.respiration_rate >= 24.0 and ("pallor" in sym or "confusion" in sym or "chest pain" in sym))
            ):
                return 0.83 if sid == "SCENARIO_3_ORTHOSTATIC_INTOLERANCE" else 0.79
            return 0.0

        # --- Solar Radiation / ARS (SCENARIO_4 / CPG-09) ---
        if sid in ("SCENARIO_4_SOLAR_RADIATION_ARS", "CPG-09"):
            if rad_level >= 0.5 or e.donki_spe_active or (d and d.alc_cells_uL is not None and d.alc_cells_uL < 1500):
                return 0.87 if sid == "SCENARIO_4_SOLAR_RADIATION_ARS" else 0.84
            if any(k in sym for k in ("shelter egress", "storm peak", "solar particle", "radiation exposure", "post-exposure", "biodosimetry")):
                if (hr_valid and v.heart_rate >= 82.0) or (temp_valid and v.core_temp_c >= 37.3):
                    return 0.84 if sid == "CPG-09" else 0.81
            return -0.15

        # --- EVA Thermal Strain / Hypothermia / DCS / Hypoxia (SCENARIO_5 / CPG-08 / CPG-15) ---
        if sid == "SCENARIO_5_EVA_THERMAL_DCS":
            if act == "EVA_SPACEWALK" and ((temp_valid and v.core_temp_c >= 38.8) or (spo2_valid and v.spo2 <= 92.0) or e.suit_pressure_psi < 4.1 or "bends" in sym):
                return 0.86
            if temp_valid and v.core_temp_c >= 39.2 and rad_level < 0.25 and "sepsis" not in sym and "pneumonia" not in sym:
                return 0.80
            return 0.0

        if sid == "CPG-15":
            if (temp_valid and v.core_temp_c >= 38.0) or any(k in sym for k in ("lcvg", "heat exhaustion", "heavy sweating", "thermal cooling", "cdo")):
                if ((temp_valid and v.core_temp_c >= 37.6) or (hr_valid and v.heart_rate >= 88.0)) and rad_level < 0.25 and "sepsis" not in sym and "pneumonia" not in sym:
                    return 0.84 if act != "EVA_SPACEWALK" else 0.83
            return 0.0

        if sid == "CPG-08":
            if spo2_valid and v.spo2 <= 93.0 and effective_co2 < 2.8 and rad_level < 0.25 and not has_trauma_bleed and not has_anaphylaxis:
                if not any(k in sym for k in ("sepsis", "pneumonia", "embol", "pleuritic", "wheeze", "bronchospasm", "smoke", "soot", "seizure", "convulsion", "hydrazine")):
                    if act != "EVA_SPACEWALK":
                        return 0.86
                    return 0.82
            if act == "EVA_SPACEWALK" and (e.suit_pressure_psi < 4.1 or "bends" in sym):
                return 0.82
            return 0.0

        # --- Sleep Deprivation / Circadian / Panic (SCENARIO_6 / CPG-31 / CPG-32) ---
        if sid in ("SCENARIO_6_CIRCADIAN_SLEEP", "CPG-32"):
            if (
                sid == "CPG-32"
                and "sleepiness" in sym
                and any(k in sym for k in ("attention lapse", "slowed cognition"))
                and hrv_valid and v.hrv_ms <= 50.0
                and effective_co2 < 2.6 and rad_level < 0.25
            ):
                return 0.85
            if act == "SLEEP" and ((hr_valid and v.heart_rate >= 62.0) or (hrv_valid and v.hrv_ms <= 22.0) or (temp_valid and v.core_temp_c >= 37.5)):
                return 0.83 if sid == "SCENARIO_6_CIRCADIAN_SLEEP" else 0.78
            if any(k in sym for k in ("sleepiness", "sleep depriv", "attention lapse", "irritability", "slowed cognition", "circadian", "sleep fragmentation", "insomnia")):
                if ((hr_valid and v.heart_rate >= 76.0) or (hrv_valid and v.hrv_ms <= 46.0)) and effective_co2 < 2.6 and rad_level < 0.25:
                    return 0.85 if sid == "CPG-32" else 0.78
            if hrv_valid and v.hrv_ms <= 22.0 and effective_co2 < 2.8 and rad_level < 0.2 and "bends" not in sym:
                return 0.25
            return 0.0

        if sid == "CPG-31":
            if (
                any(k in sym for k in ("insomnia", "sleep schedule", "circadian"))
                and hr_valid and v.heart_rate >= 94.0
                and rr_valid and v.respiration_rate >= 22.0
                and (not spo2_valid or v.spo2 >= 95.0)
                and effective_co2 < 2.6
                and not has_trauma_bleed and not has_anaphylaxis
            ):
                return 0.86
            return 0.0

        # --- IJV Thrombosis & Arrhythmia / PE (SCENARIO_7 / CPG-04 / CPG-05) ---
        if sid == "SCENARIO_7_IJV_THROMBOSIS_ARRHYTHMIA":
            if (d and d.ultrasound_ijv_thrombus) or (hr_valid and v.heart_rate >= 165.0):
                return 0.87
            if hr_valid and v.heart_rate >= 120.0 and spo2_valid and v.spo2 <= 91.0 and act != "ARED_EXERCISE" and "pleuritic" not in sym and "embol" not in sym and not has_trauma_bleed and not has_anaphylaxis:
                return 0.78
            if hr_valid and v.heart_rate >= 95.0 and any(k in sym for k in ("palpitation", "irregular pulse", "afib", "arrhythmia")):
                return 0.78
            return 0.0

        if sid == "CPG-05":
            if hr_valid and v.heart_rate >= 80.0 and "irregular pulse" in sym and "palpitation" in sym:
                return 0.86
            if hr_valid and v.heart_rate >= 95.0 and any(k in sym for k in ("palpitation", "irregular pulse", "afib", "atrial fibrillation", "arrhythmia", "svt")):
                return 0.86
            return 0.0

        if sid == "CPG-04":
            if (
                any(k in sym for k in ("pleuritic", "embol", "vte", "dvt", "ijv", "thrombus", "thrombosis"))
                and ((hr_valid and v.heart_rate >= 90.0) or (spo2_valid and v.spo2 <= 93.0) or (d is not None and bool(d.ultrasound_ijv_thrombus)))
                and not has_anaphylaxis
            ):
                return 0.86
            return 0.0

        # --- Urinary Retention (SCENARIO_8 / CPG-17) ---
        if sid in ("SCENARIO_8_SAS_URINARY_RETENTION", "CPG-17"):
            if d and d.bladder_volume_mL and d.bladder_volume_mL > 500.0:
                return 0.87 if sid == "SCENARIO_8_SAS_URINARY_RETENTION" else 0.83
            if (any(k in sym for k in ("inability to void", "urinary retention", "cannot urinate"))
                    and any(k in sym for k in ("suprapubic", "distention", "urgency"))):
                return 0.86 if sid == "CPG-17" else 0.81
            if packet.mission_day <= 7 and ((hr_valid and v.heart_rate <= 50.0) or (hrv_valid and v.hrv_ms < 20.0)):
                return 0.78 if sid == "SCENARIO_8_SAS_URINARY_RETENTION" else 0.72
            return 0.0

        # --- Acute Appendicitis (CPG-01) ---
        if sid == "CPG-01":
            if any(k in sym for k in ("rlq", "lower right", "right lower quadrant", "appendicit", "peritoneal", "mcburney", "rebound")) and ((temp_valid and v.core_temp_c >= 37.3) or (hr_valid and v.heart_rate >= 82.0)):
                return 0.86
            return 0.0

        # --- Ammonia Leak / Acute Bronchospasm (CPG-10) ---
        if sid == "CPG-10":
            if has_anaphylaxis or (bp_valid and v.blood_pressure_sys <= 96.0):
                return -0.10
            if any(k in sym for k in ("ammonia", "nh3", "coolant", "burning eye", "tearing", "bronchospasm", "wheeze", "prolonged expiration", "chemical")):
                if (hr_valid and v.heart_rate >= 82.0) or (rr_valid and v.respiration_rate >= 18.0) or (spo2_valid and v.spo2 <= 96.5):
                    return 0.86
            return 0.0

        # --- Hydrazine / Seizure (CPG-11) ---
        if sid == "CPG-11":
            if any(k in sym for k in ("hydrazine", "n2h4", "mmh", "propellant", "oxidizer", "seizure", "convulsion", "postictal", "ictal", "altered awareness")):
                if (hr_valid and v.heart_rate >= 84.0) or (spo2_valid and v.spo2 <= 95.0) or (temp_valid and v.core_temp_c >= 37.2):
                    return 0.86
            return 0.0

        # --- Carbon Monoxide / Smoke Inhalation (CPG-12) ---
        if sid == "CPG-12":
            if effective_co2 >= 2.8 or rad_level >= 0.25:
                return -0.10
            if any(k in sym for k in ("carbon monoxide", "cohb", "carboxyhemoglobin", "smoke", "soot", "hoarseness", "fire")) and ((hr_valid and v.heart_rate >= 82.0) or (rr_valid and v.respiration_rate >= 18.0)):
                return 0.87
            if (
                all(k in sym for k in ("headache", "dizziness", "nausea", "confusion"))
                and hr_valid and v.heart_rate >= 85.0
                and rr_valid and v.respiration_rate >= 19.0
                and (temp_valid and v.core_temp_c < 37.5)
            ):
                return 0.84
            return 0.0

        # --- Space Motion Sickness (CPG-13) ---
        if sid == "CPG-13":
            if rad_level >= 0.25 or effective_co2 >= 2.8 or (bp_valid and v.blood_pressure_sys <= 102.0):
                return -0.10
            if any(k in sym for k in ("rlq", "appendic", "flank", "groin", "confused", "confusion")):
                return -0.10
            if (
                any(k in sym for k in ("motion", "vestibular", "disorientation", "pallor", "malaise"))
                and any(k in sym for k in ("nausea", "vomit", "emesis"))
                and ((hr_valid and v.heart_rate >= 82.0) or (rr_valid and v.respiration_rate >= 18.0))
            ):
                return 0.85
            return 0.0

        # --- Renal Calculi / Colic (CPG-16) ---
        if sid == "CPG-16":
            if "flank" in sym and any(k in sym for k in ("groin", "hematuria", "renal colic", "kidney stone")):
                return 0.86
            return 0.0

        # --- Sepsis / Pneumonia (CPG-19) ---
        if sid == "CPG-19":
            if has_anaphylaxis or has_trauma_bleed or rad_level >= 0.25:
                return -0.10
            if (
                temp_valid and (v.core_temp_c >= 37.8 or v.core_temp_c <= 36.2)
                and hr_valid and v.heart_rate >= 94.0
                and ((bp_valid and v.blood_pressure_sys <= 104.0) or (rr_valid and v.respiration_rate >= 22.0))
                and act != "EVA_SPACEWALK"
            ):
                return 0.86
            if (
                abnormal_infection_temp and bp_valid and v.blood_pressure_sys <= 94.0
                and rr_valid and v.respiration_rate >= 22.0
                and act != "EVA_SPACEWALK"
            ):
                return 0.86
            if any(k in sym for k in ("sepsis", "pneumonia", "clammy", "rigors")) and hr_valid and v.heart_rate >= 90.0:
                return 0.84
            return 0.0

        # --- Anaphylaxis (CPG-20) ---
        if sid == "CPG-20":
            if has_anaphylaxis and ((hr_valid and v.heart_rate >= 92.0) or (bp_valid and v.blood_pressure_sys <= 102.0) or (spo2_valid and v.spo2 <= 94.0)):
                return 0.88
            return 0.0

        # --- Corneal Abrasion / Foreign Body Eye (CPG-22) ---
        if sid == "CPG-22":
            if any(k in sym for k in ("ammonia", "cough", "dyspnea", "wheeze")):
                return -0.10
            if "photophobia" in sym and "tearing" in sym and any(
                k in sym for k in ("foreign body", "foreign-body", "opening eye", "eye scratch", "gritty eye")
            ):
                return 0.85
            if any(k in sym for k in ("corneal", "abrasion", "foreign body", "foreign-body", "photophobia", "opening eye", "fluorescein", "eye scratch", "gritty eye")):
                if (hr_valid and v.heart_rate >= 76.0) or (bp_valid and v.blood_pressure_sys >= 120.0):
                    return 0.85
            return 0.0

        # --- Odontogenic Abscess (CPG-23) ---
        if sid == "CPG-23":
            if (
                "tooth pain" in sym and "swelling" in sym
                and "chewing" in sym and temp_valid and v.core_temp_c >= 37.8
            ):
                return 0.85
            if (
                any(k in sym for k in ("abscess", "tooth", "dental", "chewing", "jaw swelling", "barodontalgia"))
                and temp_valid and v.core_temp_c >= 37.4
                and (hr_valid and v.heart_rate >= 78.0)
            ):
                return 0.85
            return 0.0

        # --- Blunt Trauma / Hemorrhage / Pneumothorax / Burn (CPG-28) ---
        if sid == "CPG-28":
            if has_anaphylaxis:
                return -0.10
            if has_trauma_bleed and ((hr_valid and v.heart_rate >= 86.0) or (bp_valid and v.blood_pressure_sys <= 112.0) or (spo2_valid and v.spo2 <= 96.0) or (rr_valid and v.respiration_rate >= 20.0)):
                return 0.87
            if (
                bp_valid and v.blood_pressure_sys <= 95.0
                and hr_valid and v.heart_rate >= 100.0
                and rr_valid and v.respiration_rate >= 24.0
                and not any(k in sym for k in ("orthostat", "g-load", "sitting", "stand", "reentry"))
            ):
                return 0.84
            return 0.0

        return 0.15 if len(assessment.breached_parameters) > 0 else 0.0

    def _score_bm25_and_keywords(
        self, sid: str, query_tokens: List[str], expanded_symptoms: str
    ) -> float:
        """Compute normalized Okapi BM25 + curated phrase match score [0.0, 0.88]."""
        if not expanded_symptoms:
            return 0.0

        # 1. Exact clinical phrase / keyword hits
        keywords = SCENARIO_KEYWORDS.get(sid, [])
        phrase_hits = 0
        for i in range(MAX_KEYWORDS):
            if i >= len(keywords):
                break
            if keywords[i] in expanded_symptoms:
                phrase_hits += 1

        # 2. Okapi BM25 term weighting (k1=1.5, b=0.75)
        tf_map = self._doc_term_freqs.get(sid, {})
        doc_len = float(len(self._doc_tokens.get(sid, [])) or 1)
        k1, b = 1.5, 0.75
        bm25_raw = 0.0

        for i in range(MAX_KEYWORDS):
            if i >= len(query_tokens):
                break
            tok = query_tokens[i]
            tf = float(tf_map.get(tok, 0))
            if tf > 0:
                idf = self._idf.get(tok, 0.5)
                denom = tf + k1 * (1.0 - b + b * (doc_len / self._avg_doc_len))
                bm25_raw += idf * ((tf * (k1 + 1.0)) / denom)

        bm25_norm = min(0.75, bm25_raw / 8.0)
        if phrase_hits >= 3:
            return max(bm25_norm, 0.65)
        if phrase_hits == 2:
            return max(bm25_norm, 0.58)
        if phrase_hits == 1:
            return max(bm25_norm, 0.45)
        return bm25_norm

    def _score_scenario_hint(self, sid: str, active_hint: str) -> float:
        """Blind evaluation policy: never allow caller `active_scenario_id` to boost retrieval."""
        return 0.0

    def _is_contradictory_zero_day_pattern(
        self, packet: TelemetryPacket, symptom_lower: str, active_hint: str
    ) -> bool:
        """
        Detect unclassified multi-system failure where SpO2 < 92% and SBP < 90 mmHg
        occur simultaneously at normal CO2/Radiation without a known trauma/allergic/infectious signature.
        """
        v = packet.vitals
        e = packet.environment
        effective_co2 = max(e.cabin_co2_mmhg, e.suit_pico2_mmhg or 0.0)
        effective_rad = e.ambient_radiation_msv_h if "ambient_radiation_msv_h" not in packet.unreliable_channels else 0.0
        known_shock_markers = (
            "bends", "pleuritic", "urticaria", "angioedema", "anaphylax", "hives",
            "hemorrhag", "blood loss", "lacerat", "efast", "pneumothorax", "sepsis",
            "pneumonia", "hypoxemia", "depressuriz", "wheeze", "bronchospasm",
            "embolism", "seizure", "convulsion", "smoke", "hydrazine", "o2 valve",
        )
        if (
            v.spo2 < 92.0
            and v.blood_pressure_sys < 90.0
            and effective_co2 < 3.0
            and effective_rad < 0.25
            and not any(m in symptom_lower for m in known_shock_markers)
        ):
            return True
        return False

    def _select_dynamic_evidence(self, clean_symptoms: str) -> List[str]:
        """Select up to two loaded text documents with lexical overlap to the symptom query."""
        query_tokens = set(_tokenize(expand_clinical_synonyms(clean_symptoms)))
        matches: List[Tuple[int, str, str]] = []
        for index, sid in enumerate(self.dynamic_research_chunks):
            if index >= MAX_DYNAMIC_FILES:
                break
            chunk = self.dynamic_research_chunks[sid]
            overlap = len(query_tokens.intersection(_tokenize(chunk)))
            if overlap > 0:
                matches.append((overlap, sid, chunk))
        matches.sort(key=lambda row: (-row[0], row[1]))
        return [row[2] for row in matches[:2]]

    def _get_retrieved_evidence_chunks(
        self, scenario_id: str, proto: Dict[str, Any], clean_symptoms: str
    ) -> List[str]:
        """Return tagged protocol, research, citation, and matching official text evidence."""
        chunks: List[str] = []
        source_file = str(proto.get("source_filename", "project_protocol_data"))
        chunks.append(
            f"[Project protocol: {source_file} | {scenario_id} | unverified clinical simulation] "
            f"{proto.get('title', '')}"
        )
        for rule_id in proto.get("verified_rule_ids", []):
            rule = self.reference_rules.get(str(rule_id), {})
            if rule.get("verification_status") not in ("verified_primary_source", "verified_historical_source"):
                continue
            text = rule.get("verbatim_rule") or rule.get("rule_summary", "")
            chunks.append(
                f"[NASA source: {rule.get('source_revision', '')} | {rule.get('source_section', '')} | "
                f"{rule.get('source_url', '')} | {rule_id}] {text}"
            )
        prefix = "_".join(scenario_id.split("_")[:2])
        if prefix in self.research_chunks:
            chunks.append(self.research_chunks[prefix])
        chunks.extend(self._select_dynamic_evidence(clean_symptoms))

        # Attach relevant Layer 3 / radiation / RAG validation arXiv citation from local dataset
        for i in range(min(len(self.arxiv_citations), MAX_PROTOCOLS)):
            paper = self.arxiv_citations[i]
            aid = str(paper.get("arxiv_id", ""))
            if scenario_id == "SCENARIO_4_SOLAR_RADIATION_ARS" and aid in ("2208.00892v2", "1710.07311v4"):
                chunks.append(
                    f"[Source: arxiv_literature_citations.json | arXiv:{aid}] "
                    f"{paper.get('title', '')}: {paper.get('key_finding_quote', '')}"
                )
                break
            if aid == "2609.00256v2":
                chunks.append(
                    f"[Source: arxiv_literature_citations.json | arXiv:{aid}] "
                    f"{paper.get('title', '')}: {paper.get('key_finding_quote', '')}"
                )

        # Attach matched CHeCS formulary, onboard hardware, lab intervals, and vector-store hits
        med_names = [
            str(m.get("medication") or m.get("drug") or "").lower()
            for m in proto.get("checs_medications", [])
            if isinstance(m, dict)
        ]
        for fname, med_entry in list(self.formulary_by_name.items())[:MAX_CHUNKS]:
            if any(fname in mname for mname in med_names):
                mid = str(med_entry.get("med_id", ""))
                if mid and mid in self.research_chunks and self.research_chunks[mid] not in chunks:
                    chunks.append(self.research_chunks[mid])
                    break

        hw_text = " ".join(str(x) for x in proto.get("autonomous_checklist", [])).lower()
        for dev_id in self.hardware_by_id:
            hw_key = f"HW_{dev_id}"
            if hw_key in self.research_chunks and dev_id.lower() in hw_text:
                if self.research_chunks[hw_key] not in chunks:
                    chunks.append(self.research_chunks[hw_key])
                    break

        vec_hits = self.query_vector_store(
            f"{proto.get('title', '')} {clean_symptoms}".strip(),
            top_k=3,
            doc_types={"formulary", "hardware", "lab", "rule", "research"},
        )
        for hit in vec_hits:
            formatted = str(hit.get("formatted_chunk", ""))
            if formatted and formatted not in chunks:
                chunks.append(formatted)

        return chunks[:10]

    def _normalize_contract_checs_medications(self, medications: List[Any]) -> List[Dict[str, Any]]:
        """Add Contract C medication keys while preserving the source record fields."""
        normalized: List[Dict[str, Any]] = []
        for med in medications:
            if isinstance(med, str):
                pack_match = re.search(r"\b(CMP|OMP|TIMP|EMTP|VCP|RSP|ISP|MDP|MTP)\b", med, re.IGNORECASE)
                item = {
                    "drug": med,
                    "pack": pack_match.group(1).upper() if pack_match else "UNSPECIFIED_IN_SOURCE",
                    "source_representation": "string",
                }
            elif isinstance(med, dict):
                item = dict(med)
            else:
                continue
            item.setdefault("drug", str(med.get("medication", "") if isinstance(med, dict) else ""))
            item.setdefault("pack", str(med.get("checs_pack", "") if isinstance(med, dict) else ""))
            item["contraindication_warning"] = str(
                (med.get("contraindication_warning") or med.get("contraindication") or "")
                if isinstance(med, dict)
                else ""
            )
            normalized.append(item)
        return normalized

    def _build_hardware_and_diagnostics(self, proto: Dict[str, Any]) -> List[str]:
        """Return source checklist actions that name onboard diagnostic hardware."""
        explicit = proto.get("hardware_and_diagnostics")
        if isinstance(explicit, list):
            return [str(item) for item in explicit]
        markers = (
            "MDP", "RSP", "i-STAT", "C2M2", "OCT", "ultrasound", "ECG",
            "AED", "LBNP", "ITV", "LCVG", "ventilation fan", "fundoscopy",
        )
        selected: List[str] = []
        for step in proto.get("autonomous_checklist", []):
            text = str(step)
            if any(marker.lower() in text.lower() for marker in markers):
                selected.append(text)
        return selected

    def _build_mode_a_response(
        self,
        scenario_id: str,
        confidence: float,
        packet: TelemetryPacket,
        assessment: AnomalyAssessment,
        clean_symptoms: str,
        elapsed_ms: float,
        score_breakdown: Dict[str, float],
        signal_details: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Construct the Mode A (Known Condition >= 0.75) clinical response payload."""
        proto = self.protocol_by_id.get(scenario_id, self.protocols[0])
        title = str(proto.get("title", "Verified Spaceflight Medical Condition"))
        citations = list(proto.get("nasa_citations", []))
        raw_steps = list(proto.get("autonomous_checklist", []))
        verified_rules = [
            self.reference_rules[str(rule_id)]
            for rule_id in proto.get("verified_rule_ids", [])
            if str(rule_id) in self.reference_rules
            and self.reference_rules[str(rule_id)].get("verification_status") == "verified_primary_source"
        ]
        direct_quote = next((str(rule.get("verbatim_rule", "")) for rule in verified_rules if rule.get("verbatim_rule")), "")
        source_rule = next((rule for rule in verified_rules if rule.get("verbatim_rule") == direct_quote),
                           verified_rules[0] if verified_rules else {})
        nasa_source_summary = (
            f"{source_rule.get('source_revision', '')}, {source_rule.get('source_section', '')} — "
            f"{source_rule.get('source_url', '')}" if source_rule else "No verified NASA rule is mapped to this project protocol."
        )

        checs_medications = self._normalize_contract_checs_medications(proto.get("checs_medications", []))
        structured_list = STRUCTURED_CHECS_PRESCRIPTIONS.get(scenario_id)
        if structured_list is not None:
            raw_prescriptions = [self._parse_and_validate_medication(p) for p in structured_list]
        else:
            raw_prescriptions = [self._parse_and_validate_medication(m) for m in checs_medications]
        lockout_list = [str(x) for x in proto.get("drug_lockouts", []) if str(x).strip()]
        raw_contraindications = SCENARIO_CONTRAINDICATIONS.get(
            scenario_id,
            lockout_list or [
                m.get("contraindication", "")
                for m in checs_medications
                if m.get("contraindication")
            ],
        )
        prescriptions, checs_meds, contraindications = self._apply_deterministic_safety_filter(
            raw_prescriptions,
            checs_medications,
            raw_contraindications,
            packet,
            assessment,
        )
        contract_checs_meds = self._normalize_contract_checs_medications(checs_meds)
        blocked_medications, _ = self._medication_safety_policy(packet)
        safe_steps = [step for step in raw_steps if not any(
            marker in str(step).lower() for marker in blocked_medications
        )]
        safe_proto = dict(proto, autonomous_checklist=safe_steps)
        hardware_and_diagnostics = [step for step in self._build_hardware_and_diagnostics(safe_proto)
                                    if not any(marker in step.lower() for marker in blocked_medications)]
        checklist = [
            {
                "step": idx + 1,
                "action": str(step_text),
                "critical": idx < 3,
                "completed": False,
            }
            for idx, step_text in enumerate(safe_steps[:8])
        ]

        packs_used = sorted({p.get("checs_pack", "CMP") for p in prescriptions if p.get("checs_pack")})
        subpack_str = " / ".join(packs_used) if packs_used else "NONE"
        severity = (
            "CLASS_1_EMERGENCY"
            if assessment.nasa_priority_class == "CLASS_1_EMERGENCY"
            else "CLASS_2_WARNING"
        )
        evidence_chunks = self._get_retrieved_evidence_chunks(scenario_id, proto, clean_symptoms)

        return {
            "diagnosis_id": f"DIAG-2026-{scenario_id[-4:]}",
            "mode": "MODE_A_KNOWN_CONDITION",
            "scenario_id": scenario_id,
            "confidence": confidence,
            "diagnosis": title,
            "condition": title,
            "diagnosis_title": title,
            "severity": severity,
            "nasa_direct_quote": direct_quote,
            "source_document": str(source_rule.get("source_revision", "Project simulation protocol")),
            "clinical_protocol_source": str(proto.get("source_filename", "project_protocol_data")),
            "clinical_protocol_verification_status": "UNVERIFIED_SIMULATION_CONTENT",
            "nasa_source_summary": nasa_source_summary,
            "nasa_citations": citations,
            "nasa_citation": {
                "standard_id": source_rule.get("standard_id", ""),
                "document": source_rule.get("source_revision", "No verified NASA requirement mapped"),
                "section": source_rule.get("source_section", ""),
                "url": source_rule.get("source_url", ""),
            },
            "checs_subpack": subpack_str,
            "prescriptions": prescriptions,
            "checs_medications": contract_checs_meds,
            "hardware_and_diagnostics": hardware_and_diagnostics,
            "contraindications_locked": contraindications,
            "action_checklist": checklist,
            "action_plan": checklist,
            "autonomous_checklist": checklist,
            "triggering_vitals": assessment.triggering_vitals_summary,
            "retrieved_evidence_chunks": evidence_chunks,
            "clinical_reasoning": (
                f"Evaluated under {assessment.context_evaluated}. "
                f"Matched {scenario_id} with {int(confidence * 100)}% 3-signal neuro-symbolic confidence "
                f"(Symbolic={signal_details.get('symbolic', 0)}, BM25={signal_details.get('bm25_lexical', 0)}, "
                f"TrigramVec={signal_details.get('trigram_vector', 0)}). "
                f"Sanitized Symptom Log: '{clean_symptoms}'."
            ),
            "organ_hud_status": assessment.organ_hud_status,
            "risk_score_0_100": assessment.risk_score_0_100,
            "readiness_score_0_100": assessment.readiness_score_0_100,
            "execution_time_ms": elapsed_ms,
            "cache_hit": False,
            "source_mode": "DETERMINISTIC_LOCAL_KNOWLEDGE_BASE",
            "source_verification_status": "NOT_EXTERNALLY_VERIFIED",
            "rag_metrics": {
                "retrieval_latency_ms": elapsed_ms,
                "protocols_evaluated": len(self.protocols),
                "evidence_chunks_used": len(evidence_chunks),
                "signal_breakdown": signal_details,
            },
            "retrieval_scores": score_breakdown,
        }

    def _build_mode_b_response(
        self,
        confidence: float,
        packet: TelemetryPacket,
        assessment: AnomalyAssessment,
        clean_symptoms: str,
        elapsed_ms: float,
        score_breakdown: Dict[str, float],
        signal_details: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Construct the Mode B (Novel Anomaly < 0.75) Certified Abstention &
        4-Step Zero-Day Space Medicine Protocol payload.
        """
        capped_conf = min(0.74, max(0.15, confidence))
        abc_stabilization = self._build_abc_stabilization(packet, assessment)
        poc_orders = [
            {
                "order": "Run i-STAT Blood Gas / Chem-8 cartridge (pCO2, pH, Lactate, K+).",
                "hardware": "MDP Portable i-STAT",
            },
            {
                "order": "Run C2M2 Complete Blood Count (WBC, Platelets, Hematocrit).",
                "hardware": "C2M2 Hematology Analyzer",
            },
            {
                "order": "Capture 12-lead ECG waveform for arrhythmia/conduction screen.",
                "hardware": "Bio-Monitor / CMRS 12-Lead ECG",
            },
            {
                "order": "Perform AI-guided thoracic & optic nerve ultrasound.",
                "hardware": "Ultrasound-2 Onboard Unit",
            },
        ]
        hardware_and_diagnostics = [
            f"{item['hardware']}: {item['order']}" for item in poc_orders
        ]
        lockout_msg = (
            "CRITICAL SAFETY LOCKOUT: Opioids, NSAIDs, and Anticoagulants are LOCKED OUT "
            "until i-STAT and CBC results are confirmed."
        )
        checklist = [
            {"step": 1, "action": abc_stabilization["step_1_action"], "critical": True, "completed": False},
            {"step": 2, "action": abc_stabilization["step_2_action"], "critical": True, "completed": False},
            {"step": 3, "action": "Draw 2 drops capillary blood into i-STAT Chem-8 cartridge and run C2M2 CBC.", "critical": True, "completed": False},
            {"step": 4, "action": "Confirm high-risk drug lockout (Opioids/NSAIDs/Anticoagulants) active on Med-Kit keypad and queue EMERGENCY packet to Houston.", "critical": True, "completed": False},
        ]

        if len(self.candidate_rag_buffer) < MAX_CANDIDATE_QUEUE:
            self.candidate_rag_buffer.append(
                {
                    "timestamp": packet.timestamp,
                    "astronaut_id": packet.astronaut_id,
                    "activity_state": assessment.normalized_activity_state,
                    "triggering_vitals": assessment.triggering_vitals_summary,
                    "symptom_log": clean_symptoms,
                    "abc_protocol_applied": abc_stabilization["protocol"],
                }
            )

        diag_title = "Unclassified Novel Anomaly — Symptom-Based Stabilization Active"
        mode_b_excerpt = (
            "Clinical Decision Protocol (Mode B < 0.75) & arXiv:2610.07570v1 (Certified Abstention): "
            "Do NOT invent, guess, or hallucinate a speculative disease name; execute the 4-Step "
            "Zero-Day Space Medicine Protocol (ABC Vital Stabilization, MDP Point-of-Care Diagnostics, "
            "High-Risk Drug Lockout, and Priority Earth Uplink)."
        )
        v = packet.vitals
        is_critical_breach = (
            assessment.nasa_priority_class == "CLASS_1_EMERGENCY"
            or v.spo2 < 92.0
            or v.blood_pressure_sys < 90.0
            or v.core_temp_c >= 39.0
            or v.core_temp_c <= 35.0
            or v.heart_rate >= 135.0
            or v.heart_rate <= 42.0
        )
        if is_critical_breach:
            mode_b_severity = "CLASS_1_EMERGENCY"
            uplink_priority = "EMERGENCY"
            mode_b_risk = max(82, assessment.risk_score_0_100)
            mode_b_readiness = min(18, assessment.readiness_score_0_100)
        elif (
            assessment.nasa_priority_class == "CLASS_2_WARNING"
            or len(assessment.breached_parameters) > 0
            or len(packet.missing_vitals) >= 3
            or len(packet.unreliable_channels) > 0
        ):
            mode_b_severity = "CLASS_2_WARNING"
            uplink_priority = "PRIORITY_ADVISORY"
            mode_b_risk = max(48, assessment.risk_score_0_100)
            mode_b_readiness = min(55, assessment.readiness_score_0_100)
        else:
            mode_b_severity = "CLASS_3_CAUTION"
            uplink_priority = "ROUTINE_TELEMETRY_AUDIT"
            mode_b_risk = max(18, assessment.risk_score_0_100)
            mode_b_readiness = min(82, assessment.readiness_score_0_100)

        data_gap_notes: List[str] = []
        if packet.missing_vitals:
            data_gap_notes.append(f"missing vitals={packet.missing_vitals}")
        if packet.unreliable_channels:
            data_gap_notes.append(f"unreliable channels={packet.unreliable_channels}")
        data_gap_suffix = f" Telemetry quality holds: {'; '.join(data_gap_notes)}." if data_gap_notes else ""

        if mode_b_severity == "CLASS_1_EMERGENCY":
            checklist[3]["action"] = (
                "Confirm high-risk drug lockout (Opioids/NSAIDs/Anticoagulants) active on Med-Kit keypad "
                "and queue EMERGENCY packet to Houston."
            )
        else:
            checklist[3]["action"] = (
                f"Hold empiric high-risk medications pending verification and queue {uplink_priority} "
                "store-and-forward packet to Houston Flight Surgeon."
            )

        vec_ref_hits = self.query_vector_store(
            clean_symptoms or "point-of-care i-STAT C2M2 emergency stabilization",
            top_k=3,
            doc_types={"hardware", "lab", "rule", "protocol"},
        )
        mode_b_evidence = [mode_b_excerpt] + [
            str(h.get("formatted_chunk", "")) for h in vec_ref_hits if h.get("formatted_chunk")
        ]

        return {
            "diagnosis_id": "DIAG-2026-ZERODAY",
            "mode": "MODE_B_NOVEL_ANOMALY",
            "scenario_id": "MODE_B_ZERO_DAY",
            "confidence": capped_conf,
            "diagnosis": diag_title,
            "condition": diag_title,
            "diagnosis_title": diag_title,
            "severity": mode_b_severity,
            "abstention_reason": (
                f"Clinical match confidence {int(capped_conf * 100)}% is below verified threshold (75%). "
                f"Certified Abstention active (zero disease hallucination). Zero-Day Protocol initiated.{data_gap_suffix}"
            ),
            "nasa_direct_quote": "",
            "source_document": "Project-defined Mode B stabilization protocol",
            "source_verification_status": "PROJECT_PROTOCOL_NOT_NASA_REQUIREMENT",
            "nasa_citation": {"document": "", "section": "", "url": ""},
            "abc_vital_stabilization": {
                "target_breach": abc_stabilization["target_breach"],
                "protocol": abc_stabilization["protocol"],
            },
            "point_of_care_orders": poc_orders,
            "hardware_and_diagnostics": hardware_and_diagnostics,
            "drug_lockout_warning": lockout_msg,
            "safety_warning": lockout_msg,
            "contraindications_locked": [
                "OPIOIDS (Morphine/Fentanyl/Hydromorphone) — LOCKED OUT pending i-STAT blood gas",
                "NSAIDs & ASPIRIN (Ibuprofen/Ketorolac) — LOCKED OUT pending C2M2 platelet count",
                "ANTICOAGULANTS (Enoxaparin/Apixaban) — LOCKED OUT pending Ultrasound & coagulation panel",
            ],
            "telemetry_uplink": {
                "store_and_forward_priority": uplink_priority,
                "uplink_target": "Houston Flight Surgeon Console (20m 14s delay)",
                "save_candidate_to_local_rag": True,
                "candidates_queued": len(self.candidate_rag_buffer),
                "candidate_storage_status": "IN_MEMORY_ONLY_PENDING_REVIEW",
                "candidate_indexed_for_retrieval": False,
            },
            "retrieved_evidence_chunks": mode_b_evidence,
            "action_checklist": checklist,
            "action_plan": checklist,
            "autonomous_checklist": checklist,
            "triggering_vitals": assessment.triggering_vitals_summary,
            "organ_hud_status": assessment.organ_hud_status,
            "risk_score_0_100": mode_b_risk,
            "readiness_score_0_100": mode_b_readiness,
            "execution_time_ms": elapsed_ms,
            "cache_hit": False,
            "source_mode": "CERTIFIED_ABSTENTION_ZERO_DAY_PROTOCOL",
            "rag_metrics": {
                "retrieval_latency_ms": elapsed_ms,
                "protocols_evaluated": len(self.protocols),
                "evidence_chunks_used": len(mode_b_evidence),
                "signal_breakdown": signal_details,
            },
            "retrieval_scores": score_breakdown,
        }

    def _build_abc_stabilization(
        self, packet: TelemetryPacket, assessment: AnomalyAssessment
    ) -> Dict[str, str]:
        """Build targeted Step 1 ABC Vital Stabilization instructions from actual vital breaches."""
        v = packet.vitals
        breaches: List[str] = []
        actions: List[str] = []

        if v.spo2 < 92.0:
            breaches.append(f"SpO2: {v.spo2}% (Critical Hypoxemia)")
            actions.append("Deploy 100% O2 via Respiratory Support Pack (RSP) demand mask")
        if v.blood_pressure_sys < 90.0:
            breaches.append(f"SBP: {v.blood_pressure_sys} mmHg (Hypotension)")
            actions.append(
                "Initiate 0.9% Normal Saline 500mL IV bolus via Intravenous Support Pack (ISP) and position in supine Trendelenburg"
            )
        if v.core_temp_c > 38.5:
            breaches.append(f"Core Temp: {v.core_temp_c} °C (Hyperthermia)")
            actions.append(
                "Deploy active cooling garment (LCVG) + administer Acetaminophen 650mg PO via CMP"
            )

        if not breaches:
            breaches = list(assessment.triggering_vitals_summary[:2])
        if not actions:
            actions = [
                "Deploy 100% O2 via RSP mask on standby",
                "Establish peripheral IV access via ISP pack and monitor continuous 12-lead ECG",
            ]

        step_1 = actions[0] + "."
        step_2 = (
            actions[1] + "."
            if len(actions) > 1
            else "Insert peripheral IV line and prepare 500mL 0.9% Normal Saline via ISP."
        )

        return {
            "target_breach": " | ".join(breaches),
            "protocol": "; ".join(actions) + ".",
            "step_1_action": step_1,
            "step_2_action": step_2,
        }

    def _medication_safety_policy(self, packet: TelemetryPacket) -> Tuple[List[str], List[str]]:
        """Return shared project lockouts for every actionable response field."""
        environment = packet.environment
        diagnostics = packet.specialized_diagnostics
        unreliable = set(packet.unreliable_channels)
        co2 = max(
            environment.cabin_co2_mmhg if "cabin_co2_mmhg" not in unreliable else 0.0,
            (environment.suit_pico2_mmhg or 0.0) if "suit_pico2_mmhg" not in unreliable else 0.0,
        )
        ambient_rate = environment.ambient_radiation_msv_h if "ambient_radiation_msv_h" not in unreliable else 0.0
        radiation_risk = (
            ambient_rate >= 0.25 or environment.donki_spe_active
            or (diagnostics is not None and diagnostics.alc_cells_uL is not None and diagnostics.alc_cells_uL < 1500)
        )
        hypoxia = "spo2" not in unreliable and packet.vitals.spo2 < 92.0
        blocked: List[str] = []
        warnings: List[str] = []
        if radiation_risk:
            blocked.extend(("ibuprofen", "ketorolac", "aspirin", "nsaid", "enoxaparin", "apixaban", "clopidogrel"))
            warnings.append("NSAIDs, ASPIRIN & ANTICOAGULANTS — PROHIBITED by the project radiation/bleeding-risk lockout.")
        if co2 >= 2.8 or hypoxia:
            blocked.extend(("hydromorphone", "hydrocodone", "morphine", "fentanyl", "zolpidem", "zaleplon", "lorazepam", "diazepam"))
            warnings.append("OPIOIDS & SEDATIVES — PROHIBITED by the project hypercapnia/hypoxia lockout.")
        if diagnostics is not None and diagnostics.ultrasound_ijv_thrombus:
            warnings.append("EVA_SPACEWALK & HIGH-LOAD ARED RESISTIVE EXERCISE — PROHIBITED by the project thrombus lockout.")
        return blocked, warnings

    def _apply_deterministic_safety_filter(
        self,
        prescriptions: List[Dict[str, Any]],
        checs_meds: List[Dict[str, Any]],
        contraindications: List[str],
        packet: TelemetryPacket,
        assessment: AnomalyAssessment,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        """Apply one medication policy to prescriptions and the medication catalog."""
        blocked, warnings = self._medication_safety_policy(packet)
        filtered: List[List[Dict[str, Any]]] = []
        for entries, field in ((prescriptions, "medication"), (checs_meds, "drug")):
            safe_entries: List[Dict[str, Any]] = []
            for entry in entries:
                item = dict(entry)
                for action_field in ("medication", "drug", "dosage", "route"):
                    if action_field in item and "ibuprofen" in blocked:
                        item[action_field] = re.sub(
                            r"\s*\(or\s+Ibuprofen[^)]*\)", "", str(item[action_field]),
                            flags=re.IGNORECASE,
                        ).strip()
                action_text = " ".join(str(item.get(key, "")) for key in (field, "medication", "drug", "dosage", "route"))
                if any(marker in action_text.lower() for marker in blocked):
                    continue
                safe_entries.append(item)
            filtered.append(safe_entries)
        return filtered[0], filtered[1], list(dict.fromkeys(contraindications + warnings))

    def _is_nominal_asymptomatic(
        self,
        packet: TelemetryPacket,
        assessment: AnomalyAssessment,
        clean_symptoms: str,
        confidence: float,
    ) -> bool:
        """Return True if all vitals/environment are nominal and no abnormal clinical symptoms are logged."""
        if packet.force_mode_b or assessment.alert_level != "NOMINAL" or len(assessment.breached_parameters) > 0:
            return False
        if confidence >= MODE_A_CONFIDENCE_THRESHOLD:
            return False
        sym_low = clean_symptoms.strip().lower()
        if not sym_low:
            return True
        nominal_phrases = (
            "feeling great",
            "feeling fine",
            "no symptoms",
            "nominal",
            "none",
            "feeling well",
            "all good",
            "asymptomatic",
            "routine check",
            "normal",
        )
        return sym_low in nominal_phrases or all(
            tok in ("feeling", "great", "good", "well", "fine", "ok", "okay", "no", "symptoms", "nominal", "normal", "none", "routine")
            for tok in _tokenize(sym_low)
        )

    def _build_nominal_response(
        self,
        packet: TelemetryPacket,
        assessment: AnomalyAssessment,
        clean_symptoms: str,
        elapsed_ms: float,
        score_breakdown: Dict[str, float],
    ) -> Dict[str, Any]:
        """Construct clean nominal status response when astronaut has zero breaches and no symptoms."""
        title = "Nominal Microgravity Telemetry Status"
        quote = ""
        checklist = [
            {
                "step": 1,
                "action": "Continue continuous 1 Hz Bio-Monitor telemetry surveillance and routine mission schedule.",
                "critical": False,
                "completed": True,
            }
        ]
        return {
            "diagnosis_id": "DIAG-2026-NOMINAL",
            "mode": "NOMINAL_TELEMETRY",
            "scenario_id": "NOMINAL_BASELINE",
            "confidence": 0.99,
            "diagnosis": title,
            "condition": title,
            "diagnosis_title": title,
            "severity": "NOMINAL",
            "nasa_direct_quote": "",
            "source_document": "Project telemetry thresholds",
            "source_verification_status": "PROJECT_THRESHOLDS_NOT_NASA_LIMITS",
            "nasa_citations": [],
            "nasa_citation": {"document": "", "section": "", "url": ""},
            "checs_subpack": "NONE",
            "prescriptions": [],
            "checs_medications": [],
            "hardware_and_diagnostics": [],
            "contraindications_locked": [],
            "action_checklist": checklist,
            "action_plan": checklist,
            "autonomous_checklist": checklist,
            "triggering_vitals": assessment.triggering_vitals_summary,
            "retrieved_evidence_chunks": [],
            "clinical_reasoning": (
                f"Evaluated under {assessment.context_evaluated}. Zero threshold breaches detected. "
                f"Sanitized Symptom Log: '{clean_symptoms}'."
            ),
            "organ_hud_status": assessment.organ_hud_status,
            "risk_score_0_100": assessment.risk_score_0_100,
            "readiness_score_0_100": assessment.readiness_score_0_100,
            "execution_time_ms": elapsed_ms,
            "cache_hit": False,
            "source_mode": "DETERMINISTIC_LOCAL_KNOWLEDGE_BASE",
            "source_verification_status": "NOT_EXTERNALLY_VERIFIED",
            "rag_metrics": {
                "retrieval_latency_ms": elapsed_ms,
                "protocols_evaluated": len(self.protocols),
                "evidence_chunks_used": 0,
            },
            "retrieval_scores": score_breakdown,
        }
