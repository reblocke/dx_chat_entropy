from __future__ import annotations

# Exact frozen prompt literals intentionally retain their original long physical lines.
# ruff: noqa: E501
from .config import CategorySpec

# Preserve the notebook's rendered prompt exactly, including the 17 spaces introduced
# at each backslash-continued source line.
SYSTEM_PROMPT = "You are a knowledgeable medical reasoning AI- an expert diagnostician.                 You must follow these rules:                 1. You identify the strongest clinical findings for or against a given diagnosis.                 2. Focus on only one category of evidence at a time.                 3. Provide output in valid JSON with no extra commentary.                 4. Comply with the user instructions below."


def generate_clinical_context_string(category: CategorySpec) -> str:
    lines = [f"Here are the particular findings of the {category.key} in this case:"]
    lines.extend(
        f"{index}. {detail.finding} is {detail.status}."
        for index, detail in enumerate(category.details, start=1)
    )
    return "\n".join(lines)


def generate_overall_gen_prompt(diagnosis: str, category: CategorySpec) -> str:
    cat_key = category.key
    category_of_info = category.description
    return f"""You are given:
- {diagnosis}: the diagnosis in question.
- {cat_key}: the single category of information to consider.\x20
  Valid categories: [hpi, hist, soc, obj, test, all-but-obj].

Definition of {cat_key}:
{category_of_info}

#### Task
1. List the top 5 pieces of information from {cat_key} that most strongly support having {diagnosis}.
2. List the top 5 pieces of information from {cat_key} that most strongly support not having {diagnosis}.

#### Constraints
- Base your reasoning on the likelihood ratio (the likelihood of the finding in patients with {diagnosis} divided by the likelihood of the finding in patients without {diagnosis}):\x20
  - Pieces of evidence with higher likelihood ratios (occur with greater frequency in patients with {diagnosis} than in patients without {diagnosis}) are stronger evidence in favor of {diagnosis} than pieces of evidence with lower likelihood ratios.
  - Pieces of evidence with -in particular- a higher specificity have higher likelihood ratios. A higher sensitivity also helps, but less so than specificity.\x20
  - Pieces of evidence with lower likelihood ratios (meaning, they much more often occur in patients without {diagnosis} than with {diagnosis}) are stronger evidence against {diagnosis} being present.\x20
  - In particular, a negative result for a test with a higher sensitivity will translate to a lower likelihood ratio, and stronger evidence against {diagnosis}
- Reason using all available sources of information (epidemiology, physiology, trials, etc.) to give your best guess.\x20
- Provide no numeric LRs, only a relative ranking.
- Return only JSON in the following structure:
    {{
      "for_diagnosis_strongest_evidence": [
        {{
          "finding": "A finding relevant to {diagnosis} from {category_of_info}",
          "explanation": "Why this finding favors {diagnosis}",
          "abbreviation_expansion": {{
            "abbreviation": "Expanded term if an abbreviation is used"
          }}
        }},
        "... (4 more items) ..."
      ],
      "against_diagnosis_strongest_evidence": [
        {{
          "finding": "A finding relevant to not having {diagnosis} from {category_of_info}",
          "explanation": "Why this finding favors that {diagnosis} is not present",
          "abbreviation_expansion": {{}}
        }},
        "... (4 more items) ..."
      ],
      "summary": "A short paragraph describing the overall rationale and key differences."
    }}
- Exactly 5 items under each list, no more, no fewer.
- Define abbreviations in 'abbreviation_expansion' if used; otherwise leave it empty.
- Do not add text outside the JSON.\x20
- Output must be syntactically valid JSON, with no trailing commas.
"""


def generate_overall_spec_prompt(diagnosis: str, category: CategorySpec) -> str:
    cat_key = category.key
    category_of_info = category.description
    clinical_context = generate_clinical_context_string(category)
    return f"""You are given:
- {diagnosis}: the diagnosis in question.
- and a list of the key clinical findings from the {cat_key} ({category_of_info}) and whether they were present or not\x20

#### Task
1. List the top 5 pieces of information from the this particular case that most strongly support having {diagnosis}.
2. List the top 5 pieces of information from the this particular case that most strongly support not having {diagnosis}.

#### Clinical Context
Here is the clinical context:\x20
{clinical_context}

#### Constraints
- Only consider the findings mentioned in the clinical context. Assume all other pieces of information are unknown (and thus do not change the likelihood of disease)
- Base your reasoning on the likelihood ratio (the likelihood of the finding in patients with {diagnosis} divided by the likelihood of the finding in patients without {diagnosis}):\x20
  - Pieces of evidence with higher likelihood ratios (occur with greater frequency in patients with {diagnosis} than in patients without {diagnosis}) are stronger evidence in favor of {diagnosis} than pieces of evidence with lower likelihood ratios.
  - Pieces of evidence with -in particular- a higher specificity have higher likelihood ratios. A higher sensitivity also helps, but less so than specificity.\x20
  - Pieces of evidence with lower likelihood ratios (meaning, they much more often occur in patients without {diagnosis} than with {diagnosis}) are stronger evidence against {diagnosis} being present.\x20
  - In particular, a negative result for a test with a higher sensitivity will translate to a lower likelihood ratio, and stronger evidence against {diagnosis}
- Reason using all available sources of information (epidemiology, physiology, trials, etc.) to give your best guess.\x20
- Provide no numeric LRs, only a relative ranking. Give the strongest piece of evidence (highest LR) first

- Return only JSON in the following structure:
    {{
      "for_diagnosis_strongest_evidence": [
        {{
          "finding": "A finding relevant to {diagnosis} from {category_of_info}",
          "explanation": "Why this finding favors {diagnosis}",
          "abbreviation_expansion": {{
            "abbreviation": "Expanded term if an abbreviation is used"
          }}
        }},
        "... (4 more items) ..."
      ],
      "against_diagnosis_strongest_evidence": [
        {{
          "finding": "A finding relevant to not having {diagnosis} from {category_of_info}",
          "explanation": "Why this finding favors that {diagnosis} is not present",
          "abbreviation_expansion": {{}}
        }},
        "... (4 more items) ..."
      ],
      "summary": "A short paragraph describing the overall rationale and key differences."
    }}

- Exactly 5 items under each list, no more, no fewer.
- If a finding is not mentioned in the clinical context, it should not be given as an answer.\x20
- Define abbreviations in 'abbreviation_expansion' if used; otherwise leave it empty.
- Do not add text outside the JSON.\x20
- Output must be syntactically valid JSON, with no trailing commas.
"""


def generate_diff_gen_prompt(
    correct_diagnosis: str,
    differential_diagnosis: str,
    category: CategorySpec,
) -> str:
    cat_key = category.key
    category_of_info = category.description
    return f"""
You are asked to identify the clinical findings that most strongly discriminate between cases of the following two diagnoses:
{correct_diagnosis} and {differential_diagnosis}.

{cat_key}: the single category of information to consider.\x20
Valid categories: [hpi, hist, soc, obj, test].

Definition of {cat_key}:
{category_of_info}

Your responses must be:
- Accurate and valid for research-level work.
- Relevant to each diagnosis's typical presentation, focusing on the **differential** likelihood ratio
  (i.e., how well a finding discriminates {correct_diagnosis} from {differential_diagnosis}).
  - Pieces of evidence with higher differential likelihood ratio (occur with greater frequency in patients with {correct_diagnosis} than in patients with {differential_diagnosis}) are stronger evidence in favor of {correct_diagnosis} than pieces of evidence with lower differential likelihood ratios.
  - Pieces of evidence with lower likelihood ratios (meaning, they much more often occur in patients without {differential_diagnosis} than with {correct_diagnosis}) are stronger evidence against {correct_diagnosis} being present.\x20
- Strictly formatted in JSON to facilitate downstream parsing.
- Explicit about any abbreviations (with definitions), if used.

### Context and Focus:
- Only consider clinical information from {category_of_info}.
- Emphasize which pieces of information best distinguish {correct_diagnosis} from {differential_diagnosis}.
- You do not need numeric likelihood ratios. Just rank the findings in order of their discriminative power.

### Task:
1. List the top 5 pieces of information (within {cat_key}) that most strongly support {correct_diagnosis} over {differential_diagnosis}.
2. List the top 5 pieces of information (within {cat_key}) that most strongly support {differential_diagnosis} over {correct_diagnosis}.

### Output Format (Strict JSON):
{{
  "diagnosisA_strongest_evidence": [
    {{
      "finding": "Relevant finding favoring {correct_diagnosis}",
      "explanation": "Short reason this finding favors {correct_diagnosis}",
      "abbreviation_expansion": {{
        "abbreviation": "Expanded term if abbreviation is used"
      }}
    }},
    "... (total of 5 items) ..."
  ],
  "diagnosisB_strongest_evidence": [
    {{
      "finding": "Relevant finding favoring {differential_diagnosis}",
      "explanation": "Short reason this finding favors {differential_diagnosis}",
      "abbreviation_expansion": {{}}
    }},
    "... (total of 5 items) ..."
  ],
  "summary": "Short paragraph describing overall rationale."
}}

### Additional Constraints:
- Each list (diagnosisA_strongest_evidence, diagnosisB_strongest_evidence) must contain exactly 5 items.
- If abbreviations are used (e.g., ACS, GERD), define them in 'abbreviation_expansion'. Otherwise, use an empty object.
- Provide no extra commentary outside of the JSON.
- Return **only** the JSON in your final answer.
""".strip()


def generate_diff_spec_prompt(
    correct_diagnosis: str,
    differential_diagnosis: str,
    category: CategorySpec,
) -> str:
    cat_key = category.key
    category_of_info = category.description
    clinical_context = generate_clinical_context_string(category)
    return f"""
You are asked to identify the clinical findings from a particular case that most strongly discriminate between cases of the following two diagnoses:
{correct_diagnosis} and {differential_diagnosis}.

You are given:
- the two diagnoses under consideration: {correct_diagnosis} and {differential_diagnosis}
- and a list of the key clinical findings from the {cat_key} ({category_of_info}) and whether they were present or not\x20
- only findings given in the clinical context are under consideration

#### Task
Your task is to identify the pieces of evidence from the clinical context that argue most strongly for one of the two diagnoses:\x20
1. List the top 5 pieces of information (from the clinical context) that most strongly support {correct_diagnosis} over {differential_diagnosis}.
2. List the top 5 pieces of information (from the clinical context) that most strongly support {differential_diagnosis} over {correct_diagnosis}.

#### Clinical Context
Here is the clinical context:\x20
{clinical_context}

#### Constraints
- Only consider the findings mentioned in the clinical context. Assume all other pieces of information are unknown (and thus do not change the likelihood of disease)
- Base your reasoning on each diagnosis' usual presentation, focusing on the **differential** likelihood ratio
  (i.e., how well a finding discriminates {correct_diagnosis} from {differential_diagnosis}).
  - Pieces of evidence with higher differential likelihood ratio (occur with greater frequency in patients with {correct_diagnosis} than in patients with {differential_diagnosis}) are stronger evidence in favor of {correct_diagnosis} than pieces of evidence with lower differential likelihood ratios.
  - Pieces of evidence with lower likelihood ratios (meaning, they much more often occur in patients without {differential_diagnosis} than with {correct_diagnosis}) are stronger evidence against {correct_diagnosis} being present.\x20
- Reason using all available sources of information (epidemiology, physiology, trials, etc.) to give your best guess.\x20
- Provide no numeric LRs, only a relative ranking. Give the strongest piece of evidence (highest LR) first
- Emphasize which pieces of information best distinguish {correct_diagnosis} from {differential_diagnosis}.

### Output Format (Strict JSON):
{{
  "diagnosisA_strongest_evidence": [
    {{
      "finding": "Relevant finding favoring {correct_diagnosis}",
      "explanation": "Short reason this finding favors {correct_diagnosis}",
      "abbreviation_expansion": {{
        "abbreviation": "Expanded term if abbreviation is used"
      }}
    }},
    "... (total of 5 items) ..."
  ],
  "diagnosisB_strongest_evidence": [
    {{
      "finding": "Relevant finding favoring {differential_diagnosis}",
      "explanation": "Short reason this finding favors {differential_diagnosis}",
      "abbreviation_expansion": {{}}
    }},
    "... (total of 5 items) ..."
  ],
  "summary": "Short paragraph describing overall rationale."
}}

- Exactly 5 items under each list, no more, no fewer.
- If a finding is not mentioned in the clinical context, it should not be given as an answer.\x20
- Define abbreviations in 'abbreviation_expansion' if used; otherwise leave it empty.
- Do not add text outside the JSON.\x20
- Output must be syntactically valid JSON, with no trailing commas.
""".strip()


def build_messages(
    surface: str,
    *,
    correct_diagnosis: str,
    target_diagnosis: str,
    comparison_diagnosis: str | None,
    category: CategorySpec,
) -> list[dict[str, str]]:
    if surface == "overall/general":
        prompt = generate_overall_gen_prompt(target_diagnosis, category)
    elif surface == "overall/specific":
        prompt = generate_overall_spec_prompt(target_diagnosis, category)
    elif surface == "differential/general":
        if comparison_diagnosis is None:
            raise ValueError("Differential prompts require comparison_diagnosis")
        prompt = generate_diff_gen_prompt(correct_diagnosis, comparison_diagnosis, category)
    elif surface == "differential/specific":
        if comparison_diagnosis is None:
            raise ValueError("Differential prompts require comparison_diagnosis")
        prompt = generate_diff_spec_prompt(correct_diagnosis, comparison_diagnosis, category)
    else:
        raise ValueError(f"Unsupported feedback surface: {surface!r}")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
