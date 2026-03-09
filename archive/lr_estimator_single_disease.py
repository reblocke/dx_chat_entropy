# ─────────────────────────────────────────────────────────────────────────────
# ARCHIVED: Single-disease LR estimator (superseded by matrix-based approach)
#
# This was the original "old version" from lr_estimator_only.ipynb cell 4.
# It estimates LRs one disease at a time by iterating over sheets in a
# multi-sheet workbook. The matrix-based approach in
# 30_one_vs_rest_estimate_lrs.ipynb
# is now preferred.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os

import pandas as pd
from openai import OpenAI
from pydantic import BaseModel


class LRResponse(BaseModel):
    value: float


def estimate_lr(diagnosis: str, info_val: str, client: OpenAI, model: str) -> float:
    """
    Calls the LLM with a prompt containing the diagnosis and a finding.
    Returns the estimated likelihood ratio as a floating point number.
    """
    lr_prompt = """You are an expert in medical diagnosis who is giving assessments of how important a piece of information is when determining whether a patient has a particularly condition. Your task is to estimate the likelihood ratio of a finding for a disease. Recall that the likelihood ratio represents how much the ratio between the odds of disease given a result for a lab value, whether a physical exam finding is present, or whether a comorbidity is present over the odds of disease when you did not know the result.
You will receive inputs in the following format; Target condition: <Condition, e.g. Patient Has: Cardiac chest pain>. Finding: <piece of information, e.g. 'Patient does not have: radiation to the neck, arm, or jaw'>.
So, for example. If the odds of a Condition Z being present was 1 (meaning 50% probability) before we knew anything, but then we got a result (Finding A) it became 2 (meaning 2:1 odds or 66% probability), then the likelihood ratio would be 2.
Given a condition and a finding, you will provide your best estimate of the likelihood ratio as a floating point number. Return your answer in valid JSON with the following schema: { 'value': <floating point number greater than 0> }.\n\n

Remember, stronger evidence in favor of a condition has a value farther above 1. Strong evidence against a diagnosis has a value farther below 1 (closer to 0). A likelihood ratio of 10 is equally strong evidence for a condition as a likelihood ratio of 0.1 is against it. Likelihood ratios near 1 represent weak evidence for or against.
And if the "patient does not have: " some feature that is almost always present, that is strong evidence against.
(pay attention for double negatives- Patient has: no tobacco and Patient does not have: tobacco are identical)

Here is how I would like you to approach the problem:
First, consider the condition you are predicting (Condition: ___). Is the condition a medical diagnosis? If so, what kind of findings are usually present in someone who has that condition. Does the condition specify a certain type of patient? If so, how does that change things?
Then, consider the finding. If a finding is much more common among patients who have the condition of interest than among patients who do not have the condition of interest, then the likelihood ratio should be high. This might be because the finding is a consequence of the disease, indicates that an enabling condition is present, indicates that a frequently comorbid condition is present, or is related to the pathology of the condition. In general, likelihood ratios over about 20 are pathognomonic, above 5 or so is extremely strong evidence in favor, above 2.5 or so is strong evidence, above 1.4 is so-so evidence, and 1-1.4 is pretty weak evidence. Conversely, if the finding is more common in people who do NOT have the condition, then the likelihood ratio should be below 0. Similarly, a likelihood ratio below 0.05 would exclude the condition in most situations, below 0.2 would be extremely strong evidence against, below 0.4 would be strong evidence against, below 0.71 is so-so, and between 0.71 and 1 is pretty weak evidence against (meaning, it just doesn't change the odds of the condition much).

Here are some hypothetical examples to consider:
    Prompt = Target condition: Cardiac Chest Pain. Finding: Patient has: Pain not worse with exertion (requires they clarify exercise 1hr after meal).
    You would reason that because cardiac chest pain is usually worse with exertion because exertion worsens cardiac demand for oxygen, and thus worsens ischemia.
    Response = {
        'value': 0.4
    }

    Prompt =  Target condition: Cardiac Chest Pain. Finding: Patient does not have: tobacco.
    You would reason that because being someone who smokes increases your risk of coronary artery disease, and thus being a never smoker means you're at less risk... but many people who have heart attacks still smoke, so it's only a weak predictor.
    Response = {
        'value': 0.75
    }

    Prompt = Target condition: Cardaic Chest Pain. Finding = Patient has: enjoys playing chess.
    You would reason that because enjoying chest has no relationship to having a heart attack.
    Response = {
        'value': 1
    }

    Prompt = Target condition: Cardiac Chest Pain. Finding = Patient has: pain located behind the sternum
    You would reason that because cardiac chest pain is often experienced behind the sternum (thus, more likely), but so are many other causes of chest pain - like GERD.
    Response = {
        'value': 1.2
    }

    Prompt = Condition: Cardiac Chest Pain. Finding = patient has: pain worse with exertion.
    You would reason that because the increased myocardial oxygen consumption worsens the pain if oxygen delivery to the myocardium is the cause, as it is in heart attacks.
    Response = {
        'value': 3.4
    }

    OK: here's the prompt.. """

    messages = [
        {"role": "system", "content": lr_prompt},
        {"role": "user", "content": f"Condition: {diagnosis}\nFinding: {info_val}"},
    ]

    kwargs = {}
    if model.startswith("o"):
        kwargs["reasoning_effort"] = "medium"

    completion = client.beta.chat.completions.parse(
        model=model,
        messages=messages,
        response_format=LRResponse,
        **kwargs,
    )

    lr_response = completion.choices[0].message.parsed
    return lr_response.value


def main(input_filename: str, output_filename: str) -> None:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model_names = ["gpt-4.1-nano-2025-04-14"]

    sheets = pd.read_excel(input_filename, sheet_name=None, header=None)

    for sheet_name, df in sheets.items():
        diagnosis = df.iloc[0, 0]

        for model in model_names:
            new_col_header = "lr_" + model
            new_col = []

            print(f"Diagnosis: '{diagnosis}', Model: '{model}'")

            for i in range(len(df)):
                if i == 0:
                    new_col.append("")
                elif i == 1:
                    new_col.append(new_col_header)
                else:
                    info_val = df.iloc[i, 0]
                    try:
                        estimated_lr = estimate_lr(diagnosis, info_val, client, model)
                    except Exception as e:
                        estimated_lr = "ERROR"
                        print(
                            f"Error estimating LR for sheet '{sheet_name}', "
                            f"row {i}, model {model}: {e}"
                        )
                    new_col.append(estimated_lr)

            df.insert(df.shape[1], new_col_header, new_col)

        sheets[sheet_name] = df

    with pd.ExcelWriter(output_filename, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False, header=False)

    print(f"Processed Excel file saved as '{output_filename}'")


if __name__ == "__main__":
    main(
        input_filename="data/processed/nnt_lrs/nnt_lrs_processed.xlsx",
        output_filename="data/processed/nnt_lrs/nnt_lrs_with_estimated.xlsx",
    )
