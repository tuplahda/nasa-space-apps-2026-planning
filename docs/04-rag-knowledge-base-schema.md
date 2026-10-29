# Layer 3 RAG Knowledge Base Schema & Protocol Cards

This document defines the exact JSON/Markdown schema for the **Layer 3 Autonomous RAG Medical Officer** knowledge base so the AI team can ingest it immediately on Day 1 of the hackathon.

---

## 1. RAG Document Chunk Schema

Every clinical protocol chunk in the vector/hybrid database follows this structured metadata format to guarantee zero-hallucination retrieval:

```json
{
  "doc_id": "JSC-48522-SCENARIO-01",
  "scenario_id": "SCENARIO_1_HYPERCAPNIA",
  "title": "Acute & Chronic Hypercapnia (CO2 Toxicity) Management",
  "standard_citations": [
    "NASA-STD-3001 Vol 2 Rev D [V2 6004]",
    "OCHMO-TB-004 (Carbon Dioxide)",
    "ISS Medical Checklist JSC-48522-E4"
  ],
  "trigger_conditions": {
    "cabin_ppCO2_mmHg": "> 3.0",
    "suit_PICO2_mmHg": "> 15.0",
    "physiological_markers": ["elevated_hr", "elevated_sbp", "elevated_rr", "suppressed_hrv_rmssd"]
  },
  "checs_medications": [
    {
      "name": "Ibuprofen",
      "dose": "400-600 mg PO",
      "subpack": "Convenience Medications Pack (CMP)",
      "indication": "CO2-induced throbbing frontal headache"
    },
    {
      "name": "Acetaminophen",
      "dose": "325-650 mg PO",
      "subpack": "Convenience Medications Pack (CMP)",
      "indication": "First-line analgesic alternative"
    }
  ],
  "strict_contraindications": [
    "NEVER administer Opioid Analgesics (Hydrocodone/Acetaminophen or injectable Hydromorphone) — depresses central respiratory drive and worsens CO2 retention/acidosis."
  ],
  "hardware_packs": [
    "Respiratory Support Pack (RSP): 100% O2 demand mask (if ppCO2 > 5.0 mmHg or trigeminal paresthesia)",
    "Medical Diagnostics Pack (MDP): i-STAT / PCBA venous/capillary blood gas cartridge"
  ],
  "closed_loop_countermeasures": [
    {
      "action_id": "ACT_RELOCATE_AND_FAN",
      "label": "Relocate crew from low-ventilation zone & deploy portable inter-module fan",
      "sim_effect": "Reduces local CO2 pocket by -0.8 mmHg/min"
    },
    {
      "action_id": "ACT_CAMRAS_SCRUBBER",
      "label": "Switch ECLSS to CAMRAS amine swing-bed / purge CDRA 4BMS zeolite bed",
      "sim_effect": "Restores cabin ppCO2 decay toward 2.0 mmHg baseline"
    },
    {
      "action_id": "ACT_ADMIN_IBUPROFEN",
      "label": "Administer Ibuprofen 400 mg PO from CMP",
      "sim_effect": "Decrements CMP Ibuprofen stock by 1; resolves headache symptom log"
    },
    {
      "action_id": "ACT_DIET_RQ_SHIFT",
      "label": "Suspend 75% VO2max ARED exercise & shift diet RQ from 0.92 to 0.85",
      "sim_effect": "Cuts crew metabolic CO2 output by 20%"
    }
  ]
}
```

---

## 2. Quick-Reference CHeCS Subpack Index (2023 MKR Redesign)

| Subpack Code | Full Name | Key Contents Indexed by Layer 3 RAG |
| :--- | :--- | :--- |
| **`CMP`** | Convenience Medications Pack (23 items) | Acetaminophen, Ibuprofen, Meclizine, Promethazine PO, Pseudoephedrine, Caffeine, Loratadine |
| **`OMP`** | Oral Medications Pack (36 items) | Ondansetron ODT, Acetazolamide, Levofloxacin, Valacyclovir, Fluconazole, Melatonin, Zaleplon, Zolpidem, Modafinil, Sertraline, Lorazepam, Tamsulosin, Nitrofurantoin, Aspirin, Clopidogrel, Atorvastatin, Metoprolol, Lisinopril |
| **`TIMP`** | Topical & Injectable Medications Pack (37 items) | Promethazine IM/IV, Ketorolac IV/IM, Tropicamide/Cyclopentolate ophthalmic drops, Ceftriaxone, Ertapenem, Diazepam IM/IV, Ziprasidone IM, Lidocaine Jelly, Oxymetazoline/Mometasone nasal sprays |
| **`EMTP`** | Emergency Medical Treatment Pack (4 items) | Epinephrine `0.1 mg/mL` (`10 mL` syringe), Flumazenil `0.1 mg/mL` (benzodiazepine reversal), Ketamine, Glycopyrrolate |
| **`VCP`** | Vascular Contingency Pack (11 items) | Enoxaparin (subcutaneous LMWH), Apixaban (oral Factor Xa inhibitor), Protamine (enoxaparin reversal), Prothrombin Complex Concentrate / PCC (apixaban reversal), Sublingual Nitroglycerin |
| **`MDP`** | Medical Diagnostics Pack | `i-STAT / PCBA` blood analyzer, C2M2 Offline CBC analyzer, OCT / Optical Biometry / Tonometry / PanOptic Fundoscope, AI-guided Ultrasound probe |
| **`RSP`** | Respiratory Support Pack | `100% O2` demand/tight-fitting mask, Intubating Laryngeal Mask Airway (ILMA), AMBU bag, Inspiratory Threshold Valve (ITV/ITD) |
| **`ISP` / `MTP`** | IV Supply Pack & Minor Treatment Pack | `0.9% Normal Saline` (`500–1,000 mL`), CHeCS IV Infusion Pump, Sterile Urethral Catheterization Kit (`JSC-48522`) |
