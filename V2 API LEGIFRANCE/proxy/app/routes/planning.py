from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional, Callable, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.intent_validator import (
    extract_explicit_refs,
    validate_legal_intent,
    build_system_feedback,
)
from app.services.plan_validator import (
    validate_extraction_plan,
    build_plan_feedback,
)
from app.services.llm_openai import OpenAILLM
from app.prompts.planning_prompts import (
    INTENT_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
)

router = APIRouter()


# -----------------------------
# Models IO
# -----------------------------

class PlanRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    as_of: Optional[str] = None  # "YYYY-MM-DD" optionnel


class PlanResponse(BaseModel):
    ok: bool
    locked_refs: Dict[str, Any]
    legal_intent: Dict[str, Any]
    extraction_plan: Dict[str, Any]
    warnings: List[str] = Field(default_factory=list)


# -----------------------------
# Prompt user builders (inject question + locked refs / intent)
# -----------------------------

def build_intent_user_prompt(question: str, locked_refs: Dict[str, Any]) -> str:
    """
    Injecte la question + références verrouillées.
    Le LLM doit recopier explicit_refs (sans ajout).
    """
    return (
        "Question utilisateur:\n"
        f"<<<{question}>>>\n\n"
        "Références explicites détectées (VERROUILLÉES). "
        "Tu dois recopier ces valeurs dans explicit_refs et tu n'as PAS le droit d'en ajouter:\n"
        f"{json.dumps(locked_refs, ensure_ascii=False)}\n\n"
        "Réponds uniquement en JSON."
    )


def build_planner_user_prompt(legal_intent: Dict[str, Any], as_of: str, question: str) -> str:
    """
    Injecte le LegalIntent + date de référence + question originale.
    """
    return (
        "Construis un ExtractionPlan exécutable à partir du LegalIntent ci-dessous.\n"
        f"Date de référence (as_of): {as_of}\n"
        f"Question originale: <<<{question}>>>\n\n"
        f"LegalIntent:\n{json.dumps(legal_intent, ensure_ascii=False)}\n\n"
        "Réponds uniquement en JSON."
    )


# -----------------------------
# Generic: call LLM -> validate -> retry
# -----------------------------

async def llm_json_with_retry(
    llm: OpenAILLM,
    system_prompt: str,
    user_prompt: str,
    validator: Callable[[Dict[str, Any]], Any],   # returns ValidationResult-like with ok/errors/warnings
    feedback_builder: Callable[[List[str]], str],
    max_retries: int = 2,
    model: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    feedback: Optional[str] = None
    last_errors: List[str] = []

    for _attempt in range(max_retries + 1):
        sys = system_prompt if feedback is None else (system_prompt + "\n\n" + feedback)
        out = await llm.complete_json(system=sys, user=user_prompt, model=model)

        res = validator(out)
        if getattr(res, "warnings", None):
            warnings.extend(res.warnings)

        if res.ok:
            return out, warnings

        last_errors = list(res.errors)
        feedback = feedback_builder(res.errors)

    raise HTTPException(
        status_code=422,
        detail={"error": "LLM_VALIDATION_FAILED", "errors": last_errors, "warnings": warnings},
    )


# -----------------------------
# Route: POST /plan
# -----------------------------

@router.post("/plan", response_model=PlanResponse)
async def plan(req: PlanRequest) -> PlanResponse:
    """
    Pipeline:
      0) locked_refs = extract_explicit_refs(question)
      1) Prompt #1 -> LegalIntent (validate + retry)
      2) if is_legal == false => plan vide (court-circuit)
      3) else Prompt #2 -> ExtractionPlan (validate + retry)
    """
    as_of = req.as_of or date.today().isoformat()

    # 0) Deterministic extraction (LOCKED)
    locked_refs = extract_explicit_refs(req.question)

    llm = OpenAILLM()

    # 1) Prompt #1: LegalIntent
    intent_user = build_intent_user_prompt(req.question, locked_refs)

    def _intent_validator(obj: Dict[str, Any]):
        return validate_legal_intent(obj, locked_refs)

    legal_intent, warn1 = await llm_json_with_retry(
        llm=llm,
        system_prompt=INTENT_SYSTEM_PROMPT,
        user_prompt=intent_user,
        validator=_intent_validator,
        feedback_builder=build_system_feedback,
        max_retries=2,
        model="gpt-4o-mini",  # tu peux changer plus tard via env ou config
    )

    is_legal = bool(((legal_intent.get("intent") or {}).get("is_legal")) is True)

    # 2) Court-circuit si non juridique
    if not is_legal:
        extraction_plan = {
            "version": "1.0",
            "meta": {"user_question": req.question, "as_of": as_of, "jurisdiction": "FR"},
            "plan": [],
            "missing_information": legal_intent.get("missing_information", []),
            "constraints": {"max_sources": 12, "must_cite_sources": True},
        }
        return PlanResponse(
            ok=True,
            locked_refs=locked_refs,
            legal_intent=legal_intent,
            extraction_plan=extraction_plan,
            warnings=warn1,
        )

    # 3) Prompt #2: ExtractionPlan
    planner_user = build_planner_user_prompt(legal_intent, as_of, req.question)

    def _plan_validator(obj: Dict[str, Any]):
        return validate_extraction_plan(obj, legal_intent, locked_refs, as_of)

    extraction_plan, warn2 = await llm_json_with_retry(
        llm=llm,
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_prompt=planner_user,
        validator=_plan_validator,
        feedback_builder=build_plan_feedback,
        max_retries=2,
        model="gpt-4o-mini",
    )

    return PlanResponse(
        ok=True,
        locked_refs=locked_refs,
        legal_intent=legal_intent,
        extraction_plan=extraction_plan,
        warnings=warn1 + warn2,
    )
