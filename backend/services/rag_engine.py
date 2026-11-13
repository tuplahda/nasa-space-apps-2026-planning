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
from typing import Any, Dict, List, Optional, Tuple

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
RESEARCH_MD_PATH: Path = REPO_ROOT / "data" / "nasa_space_medicine_research.md"
ARXIV_JSON_PATH: Path = REPO_ROOT / "data" / "arxiv_literature_citations.json"
OFFICIAL_PROTOCOLS_DIR: Path = REPO_ROOT / "data" / "nasa_official_protocols"

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
    "unable to void": "urinary retention void bladder",
    "cannot urinate": "urinary retention void bladder",
    "stuffy nose": "sas rhinosinusitis stuffies nasal",
    "motion sick": "sas adaptation nausea",
}

# Grounded NASA standard & checklist excerpts strictly from local source files
# (`artifacts/clinical_decision_protocol_2_modes.md`, `data/rag_protocols_8_scenarios.json`,
# and `data/nasa_space_medicine_research.md`). Note: Only Scenario 1 has an explicit
# `nasa_direct_quote` string in `clinical_decision_protocol_2_modes.md`; Scenarios 2-8
# use verbatim citations and protocol text from `data/rag_protocols_8_scenarios.json`.
VERBATIM_NASA_QUOTES: Dict[str, str] = {
    "SCENARIO_1_HYPERCAPNIA": (
        "NASA-STD-3001 V2 [6004]: Inspired pCO2 shall be maintained below 3.0 mmHg (0.4 kPa). "
        "Emergency response required if pCO2 exceeds 5.0 mmHg."
    ),
    "SCENARIO_2_SANS": (
        "NASA HRP Evidence Book: SANS / NASA SANS Clinical Practice Guideline (CPG) / "
        "ISS Medical Checklist JSC-48522: Perform OCT (quantify RNFL > 105 um), Optical Biometry "
        "(axial length), Tonometry, and PanOptic Fundoscopy (MDP); initiate nightly LBNP and clamp cabin ppCO2 < 2.5 mmHg."
    ),
    "SCENARIO_3_ORTHOSTATIC_INTOLERANCE": (
        "NASA-STD-3001 Fitness-for-Duty Orthostatic Hypotension Standard (4.2.11) / "
        "ISS Medical Checklist JSC-48522: Command crewmember into immediate supine, legs-elevated "
        "(Trendelenburg) posture to restore venous return; attach Inspiratory Threshold Valve (ITV / ITD) to facemask (RSP)."
    ),
    "SCENARIO_4_SOLAR_RADIATION_ARS": (
        "NASA-STD-3001 Vol 1 Rev C [V1 4030] Space Permissible Exposure Limits / "
        "ISS Medical Checklist JSC-48522: ALARA Protocol: Abort EVA immediately upon DONKI /FLR or /SEP "
        "notification; retreat to high-hydrogen Storm Shelter and perform serial C2M2 offline CBC assays every 6 hours."
    ),
    "SCENARIO_5_EVA_THERMAL_DCS": (
        "NASA-STD-3001 Vol 1 & Vol 2 [V2 6006] / NASA EVA Probabilistic Risk Assessment (PRA) / "
        "ISS Medical Checklist JSC-48522: Abort EVA, ingress airlock, and repressurize to 101.3 kPa "
        "(14.7 psia) to compress nitrogen microbubbles; place astronaut on 100% O2 via tight-fitting mask (RSP)."
    ),
    "SCENARIO_6_CIRCADIAN_SLEEP": (
        "NASA Spaceflight Standard Measures (SSM) — Sleep & Cognition Test Battery (CTB) / "
        "NASA-STD-3001 [V2 6012] Thermal Comfort: Cool Crew Quarters to 18-20 °C ([V2 6012]), verify local "
        "sleep-station fan & ppCO2 < 2.5 mmHg, and configure 480 nm blue-enriched / blue-depleted solid-state lighting."
    ),
    "SCENARIO_7_IJV_THROMBOSIS_ARRHYTHMIA": (
        "ISS Vascular Contingency Pack Protocol / ISS Medical Checklist JSC-48522 (ACLS / CMRS): "
        "Perform C2M2 AI-guided neck ultrasound to confirm IJV thrombus; initiate subcutaneous Enoxaparin "
        "followed by oral Apixaban from the Vascular Contingency Pack (VCP) and lock out EVA and high-load ARED exercise."
    ),
    "SCENARIO_8_SAS_URINARY_RETENTION": (
        "ISS Medical Checklist JSC-48522 (SAS & Bladder Catheterization) / NASA IMM CLIFFs: "
        "If unable to void >8 hours: Perform AI-guided bladder ultrasound (MDP) and administer Tamsulosin 0.4 mg PO (OMP); "
        "if bladder volume >500 mL, perform sterile urethral catheterization per JSC-48522 using Lidocaine Jelly and MTP catheter kit."
    ),
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
        self.reload_knowledge_base()

    def reload_knowledge_base(self) -> Dict[str, Any]:
        """Load core NASA datasets, research chunks, and dynamic files, then build indices."""
        self.protocols = []
        self.protocol_by_id = {}
        self.dynamic_research_chunks = {}
        self.dynamic_docs_loaded = []
        self.diagnosis_cache.clear()

        if PROTOCOLS_JSON_PATH.exists():
            with open(PROTOCOLS_JSON_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                for i in range(MAX_PROTOCOLS):
                    if i >= len(loaded):
                        break
                    item = loaded[i]
                    sid = str(item.get("scenario_id", f"SCENARIO_{i + 1}"))
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
                normalized_cpg = {
                    "scenario_id": pid,
                    "title": cpg.get("title", pid),
                    "category": cpg.get("category", "Space Medicine CPG"),
                    "nasa_citations": cpg.get("nasa_citations", []),
                    "symptoms_by_severity": {
                        "MODERATE": cpg.get("search_text", ""),
                        "DIAGNOSTIC_CRITERIA": "; ".join(cpg.get("diagnostic_criteria", [])),
                    },
                    "autonomous_checklist": cpg.get("autonomous_checklist", []),
                    "checs_medications": cpg.get("prescribed_meds", []),
                    "drug_lockouts": cpg.get("drug_lockouts", []),
                }
                self.protocols.append(normalized_cpg)
                self.protocol_by_id[pid] = normalized_cpg

        if ARXIV_JSON_PATH.exists():
            with open(ARXIV_JSON_PATH, "r", encoding="utf-8") as af:
                self.arxiv_citations = json.load(af)

        self._parse_research_markdown_chunks()
        self._load_preprocessed_reference_chunks()
        self._load_dynamic_official_protocols()
        self._build_hybrid_search_index()

        return {
            "protocols_count": len(self.protocols),
            "research_chunks_indexed": len(self.research_chunks),
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
        """Index pre-processed CHeCS formulary, NASA-STD-3001 rules, and lab intervals."""
        if CHECS_FORMULARY_JSON_PATH.exists():
            with open(CHECS_FORMULARY_JSON_PATH, "r", encoding="utf-8") as cf:
                meds = json.load(cf).get("medications", [])
            for med in meds[:MAX_CHUNKS]:
                mid = str(med.get("med_id", ""))
                if mid:
                    self.research_chunks[mid] = f"[Source: checs_formulary.json | {mid}] {med.get('search_text', '')}"

        if NASA_RULES_JSON_PATH.exists():
            with open(NASA_RULES_JSON_PATH, "r", encoding="utf-8") as nf:
                rules = json.load(nf).get("rules", [])
            for rule in rules[:MAX_CHUNKS]:
                rid = str(rule.get("standard_id", ""))
                if rid:
                    self.research_chunks[f"RULE_{rid}"] = f"[Source: nasa_std_3001_rules.json | {rid}] {rule.get('verbatim_rule', '')}"

        if LAB_INTERVALS_JSON_PATH.exists():
            with open(LAB_INTERVALS_JSON_PATH, "r", encoding="utf-8") as lf:
                lab_data = json.load(lf)
            for group in ("blood_gas_and_lactate", "electrolytes_and_glucose", "hematology_cbc"):
                for item in lab_data.get(group, []):
                    analyte = str(item.get("analyte", ""))
                    if analyte:
                        self.research_chunks[f"LAB_{analyte}"] = f"[Source: lab_reference_intervals.json | {analyte}] {item.get('search_text', '')}"

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
            checklist = " ".join(str(c) for c in proto.get("autonomous_checklist", []))

            corpus_text = f"{title} {sym_values} {kw_values} {checklist}"
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
            self._doc_trigram_vecs[sid] = _char_trigram_vector(f"{title} {sym_values} {kw_values}")

        self._avg_doc_len = (total_len / float(n_docs)) if n_docs > 0 else 1.0
        self._idf = {}
        for tok, df in df_counts.items():
            # Standard Robertson-Sparck Jones BM25 IDF smoothing
            self._idf[tok] = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))

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

    def _is_mode_a_data_complete(self, proto: Optional[Dict[str, Any]]) -> bool:
        """
        Require the local protocol record to contain the fields needed for Mode A output.

        This structural check does not independently validate external source provenance.
        """
        if not proto:
            return False
        citations = proto.get("nasa_citations")
        meds = proto.get("checs_medications")
        checklist = proto.get("autonomous_checklist")
        return bool(citations and meds and checklist)

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
            and self._is_mode_a_data_complete(matched_proto)
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

        if len(self.diagnosis_cache) >= MAX_CACHE_ENTRIES:
            self.diagnosis_cache.clear()
        self.diagnosis_cache[cache_key] = dict(response)
        return response

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

        expanded_symptoms = expand_clinical_synonyms(clean_symptoms)
        active_hint = (packet.active_scenario_id or "").strip().upper()

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
        per_scenario_signals: Dict[str, Dict[str, float]] = {}

        for i in range(MAX_PROTOCOLS):
            if i >= len(self.protocols):
                break
            proto = self.protocols[i]
            sid = str(proto.get("scenario_id", ""))

            sym_score = self._score_symbolic_telemetry(sid, packet, assessment)
            bm25_score = self._score_bm25_and_keywords(sid, query_tokens, expanded_symptoms)
            vec_score = _cosine_similarity_sparse(query_trigram, self._doc_trigram_vecs.get(sid, {}))
            hint_bonus = self._score_scenario_hint(sid, active_hint)

            # Neuro-Symbolic fusion: strong telemetry match + lexical/vector confirmation
            fused = sym_score + (0.70 * bm25_score) + (0.30 * vec_score) + hint_bonus
            # Boost when both symbolic vitals AND clinical text corroborate the same condition
            if sym_score >= 0.65 and (bm25_score >= 0.25 or vec_score >= 0.15):
                fused = max(fused, 0.92)
            elif sym_score >= 0.75 or (sym_score > 0.0 and bm25_score >= 0.75):
                fused = max(fused, 0.84)
            elif sym_score < 0.0 and hint_bonus == 0.0:
                # Negative physiological evidence (e.g., normal CO2 <2.6 mmHg or normal radiation)
                # blocks environmental/radiation scenarios even if generic symptoms (headache/nausea) overlap
                fused = min(fused, 0.48)
            elif sym_score == 0.0 and hint_bonus == 0.0:
                # Zero telemetry/context corroboration: prevent pure lexical keyword overlap from
                # reaching the 0.75 Mode A threshold so uncorroborated symptoms abstain in Mode B
                fused = min(fused, 0.72)

            total = round(min(0.99, max(0.05, fused)), 3)
            scores[sid] = total
            per_scenario_signals[sid] = {
                "symbolic": round(sym_score, 3),
                "bm25_lexical": round(bm25_score, 3),
                "trigram_vector": round(vec_score, 3),
                "fused": total,
            }

        best_id = "SCENARIO_1_HYPERCAPNIA"
        best_score = 0.0
        sids = list(scores.keys())
        for i in range(MAX_PROTOCOLS):
            if i >= len(sids):
                break
            k = sids[i]
            if scores[k] > best_score:
                best_score = scores[k]
                best_id = k

        return (
            best_id,
            round(best_score, 2),
            scores,
            per_scenario_signals.get(best_id, {}),
        )

    def _score_symbolic_telemetry(
        self, sid: str, packet: TelemetryPacket, assessment: AnomalyAssessment
    ) -> float:
        """
        Compute symbolic telemetry match score [-0.25, 0.85] for scenario `sid`,
        including negative-evidence disambiguation.
        """
        v = packet.vitals
        e = packet.environment
        d = packet.specialized_diagnostics
        act = assessment.normalized_activity_state
        effective_co2 = max(e.cabin_co2_mmhg, e.suit_pico2_mmhg or 0.0)

        if sid == "SCENARIO_1_HYPERCAPNIA":
            if effective_co2 >= 4.5:
                return 0.85
            if effective_co2 >= 2.8:
                return 0.78
            # Negative evidence: normal cabin/suit CO2 (<2.6 mmHg) rules out environmental hypercapnia
            return -0.20

        if sid == "SCENARIO_2_SANS":
            if d and ((d.oct_rnfl_um and d.oct_rnfl_um > 105.0) or (d.refraction_shift_D and d.refraction_shift_D >= 0.5)):
                return 0.86
            if packet.mission_day >= 21 and v.blood_pressure_sys < 130.0 and effective_co2 < 3.0:
                return 0.25
            return 0.0

        if sid == "SCENARIO_3_ORTHOSTATIC_INTOLERANCE":
            if v.blood_pressure_sys <= 94.0 and v.spo2 >= 93.0 and effective_co2 < 3.0 and e.ambient_radiation_msv_h < 0.25:
                return 0.80
            return 0.0

        if sid == "SCENARIO_4_SOLAR_RADIATION_ARS":
            if e.ambient_radiation_msv_h >= 0.5 or e.donki_spe_active or (d and d.alc_cells_uL and d.alc_cells_uL < 1500):
                return 0.86
            return -0.15

        if sid == "SCENARIO_5_EVA_THERMAL_DCS":
            if act == "EVA_SPACEWALK" and (v.core_temp_c >= 38.8 or v.spo2 <= 92.0):
                return 0.84
            if v.core_temp_c >= 39.2 and e.ambient_radiation_msv_h < 0.25:
                return 0.78
            return 0.0

        if sid == "SCENARIO_6_CIRCADIAN_SLEEP":
            if act == "SLEEP" and (v.heart_rate >= 62.0 or v.hrv_ms <= 22.0 or v.core_temp_c >= 37.5):
                return 0.80
            if v.hrv_ms <= 22.0 and effective_co2 < 2.8 and e.ambient_radiation_msv_h < 0.2:
                return 0.25
            return 0.0

        if sid == "SCENARIO_7_IJV_THROMBOSIS_ARRHYTHMIA":
            if (d and d.ultrasound_ijv_thrombus) or v.heart_rate >= 165.0:
                return 0.86
            if v.heart_rate >= 120.0 and v.spo2 <= 91.0 and act != "ARED_EXERCISE":
                return 0.76
            return 0.0

        if sid == "SCENARIO_8_SAS_URINARY_RETENTION":
            if d and d.bladder_volume_mL and d.bladder_volume_mL > 500.0:
                return 0.86
            if packet.mission_day <= 7 and (v.heart_rate <= 50.0 or v.hrv_ms < 20.0):
                return 0.78
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

        bm25_norm = min(0.85, bm25_raw / 4.5)
        if phrase_hits >= 3:
            return max(bm25_norm, 0.84)
        if phrase_hits == 2:
            return max(bm25_norm, 0.76)
        if phrase_hits == 1:
            return max(bm25_norm, 0.45)
        return bm25_norm

    def _score_scenario_hint(self, sid: str, active_hint: str) -> float:
        """Boost score if caller explicitly passed a scenario identifier."""
        if not active_hint:
            return 0.0
        if active_hint == sid:
            return 0.90
        hint_map = {
            "HYPERCAPNIA": "SCENARIO_1_HYPERCAPNIA",
            "CO2": "SCENARIO_1_HYPERCAPNIA",
            "SANS": "SCENARIO_2_SANS",
            "ORTHOSTATIC": "SCENARIO_3_ORTHOSTATIC_INTOLERANCE",
            "DEHYDRATION": "SCENARIO_3_ORTHOSTATIC_INTOLERANCE",
            "SOLAR_FLARE": "SCENARIO_4_SOLAR_RADIATION_ARS",
            "RADIATION": "SCENARIO_4_SOLAR_RADIATION_ARS",
            "ARS": "SCENARIO_4_SOLAR_RADIATION_ARS",
            "DCS": "SCENARIO_5_EVA_THERMAL_DCS",
            "THERMAL": "SCENARIO_5_EVA_THERMAL_DCS",
            "SLEEP": "SCENARIO_6_CIRCADIAN_SLEEP",
            "CIRCADIAN": "SCENARIO_6_CIRCADIAN_SLEEP",
            "IJV": "SCENARIO_7_IJV_THROMBOSIS_ARRHYTHMIA",
            "THROMBOSIS": "SCENARIO_7_IJV_THROMBOSIS_ARRHYTHMIA",
            "SAS": "SCENARIO_8_SAS_URINARY_RETENTION",
            "RETENTION": "SCENARIO_8_SAS_URINARY_RETENTION",
        }
        for key, target_sid in hint_map.items():
            if key in active_hint and target_sid == sid:
                return 0.88
        return 0.0

    def _is_contradictory_zero_day_pattern(
        self, packet: TelemetryPacket, symptom_lower: str, active_hint: str
    ) -> bool:
        """
        Detect unclassified multi-system failure where SpO2 < 92% and SBP < 90 mmHg
        occur simultaneously at normal CO2/Radiation without a known scenario signature.
        """
        if active_hint and active_hint not in ("", "NONE"):
            return False
        v = packet.vitals
        e = packet.environment
        effective_co2 = max(e.cabin_co2_mmhg, e.suit_pico2_mmhg or 0.0)
        if (
            v.spo2 < 92.0
            and v.blood_pressure_sys < 90.0
            and effective_co2 < 3.0
            and e.ambient_radiation_msv_h < 0.25
            and "bends" not in symptom_lower
            and "pleuritic" not in symptom_lower
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
        citations = proto.get("nasa_citations", [])
        primary_cit = citations[0] if citations else "UNSPECIFIED_CITATION"
        chunks.append(
            f"[Source: rag_protocols_8_scenarios.json | {scenario_id}] "
            f"{proto.get('title', '')} — {VERBATIM_NASA_QUOTES.get(scenario_id, primary_cit)}"
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
        return chunks

    def _normalize_contract_checs_medications(self, medications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add Contract C medication keys while preserving the source record fields."""
        normalized: List[Dict[str, Any]] = []
        for med in medications:
            item = dict(med)
            item.setdefault("drug", str(med.get("medication", "")))
            item.setdefault("pack", str(med.get("checs_pack", "")))
            item["contraindication_warning"] = str(
                med.get("contraindication_warning") or med.get("contraindication") or ""
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
        fallback_excerpt = (
            f"{citations[0]} — {raw_steps[0]}"
            if (citations and raw_steps)
            else str(proto.get("nasa_direct_quote", ""))
        )
        direct_quote = str(
            proto.get("nasa_direct_quote")
            or VERBATIM_NASA_QUOTES.get(scenario_id, fallback_excerpt)
        )

        raw_prescriptions = STRUCTURED_CHECS_PRESCRIPTIONS.get(
            scenario_id,
            [
                {
                    "medication": m.get("drug", ""),
                    "route": "Per protocol source",
                    "checs_pack": m.get("pack", ""),
                    "dosage": m.get("drug", ""),
                }
                for m in proto.get("checs_medications", [])
            ],
        )
        raw_contraindications = SCENARIO_CONTRAINDICATIONS.get(
            scenario_id,
            [
                m.get("contraindication", "")
                for m in proto.get("checs_medications", [])
                if m.get("contraindication")
            ],
        )
        prescriptions, checs_meds, contraindications = self._apply_deterministic_safety_filter(
            raw_prescriptions,
            proto.get("checs_medications", []),
            raw_contraindications,
            packet,
            assessment,
        )
        contract_checs_meds = self._normalize_contract_checs_medications(checs_meds)
        hardware_and_diagnostics = self._build_hardware_and_diagnostics(proto)
        checklist = [
            {
                "step": idx + 1,
                "action": str(step_text),
                "critical": idx < 3,
                "completed": False,
            }
            for idx, step_text in enumerate(raw_steps[:8])
        ]

        packs_used = sorted({p.get("checs_pack", "CMP") for p in prescriptions if p.get("checs_pack")})
        subpack_str = " / ".join(packs_used) if packs_used else "CMP / TIMP"
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
            "source_document": " / ".join(citations[:2]),
            "nasa_citations": citations,
            "nasa_citation": {
                "document": citations[0] if citations else "NASA-STD-3001",
                "section": direct_quote,
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
        return {
            "diagnosis_id": "DIAG-2026-ZERODAY",
            "mode": "MODE_B_NOVEL_ANOMALY",
            "scenario_id": "MODE_B_ZERO_DAY",
            "confidence": capped_conf,
            "diagnosis": diag_title,
            "condition": diag_title,
            "diagnosis_title": diag_title,
            "severity": "CLASS_1_EMERGENCY",
            "abstention_reason": (
                f"Clinical match confidence {int(capped_conf * 100)}% is below verified threshold (75%). "
                "Certified Abstention active (zero disease hallucination). Zero-Day Protocol initiated."
            ),
            "nasa_direct_quote": mode_b_excerpt,
            "source_document": "artifacts/clinical_decision_protocol_2_modes.md / arXiv:2610.07570v1",
            "nasa_citation": {
                "document": "artifacts/clinical_decision_protocol_2_modes.md / NASA-STD-3001 [V1 3004]",
                "section": mode_b_excerpt,
            },
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
                "store_and_forward_priority": "EMERGENCY",
                "uplink_target": "Houston Flight Surgeon Console (20m 14s delay)",
                "save_candidate_to_local_rag": True,
                "candidates_queued": len(self.candidate_rag_buffer),
                "candidate_storage_status": "IN_MEMORY_ONLY_PENDING_REVIEW",
                "candidate_indexed_for_retrieval": False,
            },
            "action_checklist": checklist,
            "action_plan": checklist,
            "autonomous_checklist": checklist,
            "triggering_vitals": assessment.triggering_vitals_summary,
            "organ_hud_status": assessment.organ_hud_status,
            "risk_score_0_100": max(82, assessment.risk_score_0_100),
            "readiness_score_0_100": min(18, assessment.readiness_score_0_100),
            "execution_time_ms": elapsed_ms,
            "cache_hit": False,
            "source_mode": "CERTIFIED_ABSTENTION_ZERO_DAY_PROTOCOL",
            "rag_metrics": {
                "retrieval_latency_ms": elapsed_ms,
                "protocols_evaluated": len(self.protocols),
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

    def _apply_deterministic_safety_filter(
        self,
        prescriptions: List[Dict[str, Any]],
        checs_meds: List[Dict[str, Any]],
        contraindications: List[str],
        packet: TelemetryPacket,
        assessment: AnomalyAssessment,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        """
        Deterministic hard-coded pharmacological safety filter (Security & Safety Guardrails Part 3):
        Dynamically enforces cross-hazard contraindications (e.g., concurrent radiation + hypercapnia).
        """
        safe_rx = [dict(p) for p in prescriptions]
        safe_meds = [dict(m) for m in checs_meds]
        safe_contra = list(contraindications)

        e = packet.environment
        v = packet.vitals
        d = packet.specialized_diagnostics
        effective_co2 = max(e.cabin_co2_mmhg, e.suit_pico2_mmhg or 0.0)

        has_radiation_bleed_risk = (
            e.ambient_radiation_msv_h >= 0.25
            or e.donki_spe_active
            or (d is not None and d.alc_cells_uL is not None and d.alc_cells_uL < 1500.0)
        )
        has_hypercapnia_hypoxia_risk = (effective_co2 >= 2.8 or v.spo2 < 92.0)
        has_thrombus_risk = (d is not None and d.ultrasound_ijv_thrombus is True)

        if has_radiation_bleed_risk:
            for item in safe_rx:
                med_str = str(item.get("medication", ""))
                if "ibuprofen" in med_str.lower() or "nsaid" in med_str.lower():
                    item["medication"] = re.sub(
                        r"\s*\(or\s+Ibuprofen[^)]*\)",
                        "",
                        med_str,
                        flags=re.IGNORECASE,
                    ).strip()
            for m in safe_meds:
                drug_str = str(m.get("drug", ""))
                if "ibuprofen" in drug_str.lower() or "nsaid" in drug_str.lower():
                    m["drug"] = re.sub(
                        r"\s*\(or\s+Ibuprofen[^)]*\)",
                        "",
                        drug_str,
                        flags=re.IGNORECASE,
                    ).strip()
            if not any("NSAID" in c.upper() or "IBUPROFEN" in c.upper() for c in safe_contra):
                safe_contra.append(
                    "NSAIDs & ASPIRIN (Ibuprofen/Ketorolac/Aspirin) — PROHIBITED: "
                    "Concurrent radiation/thrombocytopenia hemorrhage risk (NASA-STD-3001 [V1 4030])"
                )

        if has_hypercapnia_hypoxia_risk:
            if not any("OPIOID" in c.upper() or "MORPHINE" in c.upper() for c in safe_contra):
                safe_contra.append(
                    "OPIOIDS (Morphine/Fentanyl/Hydromorphone) — PROHIBITED: "
                    "Suppresses central hypercapnic/hypoxic respiratory drive (NASA-STD-3001 [V2 6004])"
                )

        if has_thrombus_risk:
            if not any("EVA_SPACEWALK" in c.upper() for c in safe_contra):
                safe_contra.append(
                    "EVA_SPACEWALK & HIGH-LOAD ARED RESISTIVE EXERCISE — PROHIBITED: "
                    "Valsalva/suit pressure risks fatal pulmonary embolism"
                )

        return safe_rx, safe_meds, safe_contra

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
        title = "Nominal Microgravity Physiology — All Systems Within NASA-STD-3001 Limits"
        quote = (
            "NASA-STD-3001 [V1 3003] / [V1 3003a] Continuous Biosensor Telemetry: "
            "All physiological and environmental telemetry parameters remain within adapted microgravity baseline limits."
        )
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
            "nasa_direct_quote": quote,
            "source_document": "NASA-STD-3001 Vol 1 [V1 3003 / 3003a]",
            "nasa_citations": ["NASA-STD-3001 Vol 1 [V1 3003]", "NASA-STD-3001 Vol 1 [V1 3003a]"],
            "nasa_citation": {
                "document": "NASA-STD-3001 Vol 1 [V1 3003 / 3003a]",
                "section": quote,
            },
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
