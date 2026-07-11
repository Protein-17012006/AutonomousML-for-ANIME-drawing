"""Follow-up routes on a finished session: grounded Q&A (POST /ask), artifact
download / export bundle (GET /{name}), and the draw-key re-fill loop (POST /key).
Registered LAST: GET /session/{sid}/{name} is the broadest matcher."""
from __future__ import annotations

import io
import pathlib
import zipfile

import numpy as np
from PIL import Image
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from service.annotate import annotate_explained_pairs
from service.artifacts import (build_montage, build_report, build_video, build_pair_frames)
from service.explain import explain_pairs, region_box
from service.runner import run_session, recompute_result
from service.schemas import PairEvent, ResultEvent
from service.state import _sessions, _state

router = APIRouter()


class AskReq(BaseModel):
    question: str


class AgentReq(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/session/{sid}/ask")
def post_ask(sid: int, req: AskReq):
    """Grounded Q&A about a finished session (vault 'Chat-First Copilot Surface' §3).
    Answers ONLY from the retained session facts; degrades to a deterministic
    summary when DeepSeek is unconfigured/unreachable — never 500."""
    st = _state.get(sid)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)")
    from service.ask import answer_question
    from service.director_llm import make_ask_fn
    return answer_question(st, req.question, make_ask_fn())


@router.post("/session/{sid}/agent")
def post_agent(sid: int, req: AgentReq):
    """UIA (agent #3): grounded chat + ONE validated tool proposal per turn.
    The LLM proposes, the whitelist validates, the USER confirms anything that
    costs GPU (see rerun below). Same degrade discipline as /ask — never 500."""
    st = _state.get(sid)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)")
    from service.agent import decide_agent
    from service.director_llm import make_ask_fn
    return decide_agent(st, req.message, req.history, make_ask_fn())


@router.get("/session/{sid}/{name}")
async def get_artifact(sid: int, name: str):
    if sid not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    base = pathlib.Path(_sessions[sid]).resolve()
    # Export bundle: zip the usable artifacts (reconstructed video + in-between
    # frames + montage + report) so the artist takes the result away in one click.
    if name == "bundle.zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(base.iterdir()):
                if f.is_file() and f.suffix.lower() in {".mp4", ".png", ".md"}:
                    z.write(f, arcname=f.name)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="copilot_session.zip"'},
        )
    path = (base / name).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="invalid artifact name")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(str(path))


@router.post("/session/{sid}/key")
async def post_key(sid: int, index: int = Form(...), key: UploadFile = File(...)):
    """Draw-key loop (Tier 2): the artist supplies a drawn breakdown key for gap
    `index` -> TARGETED re-fill. Mini-run the gate->interp->self-QA over just
    [key[index], drawn, key[index+1]] (the two new sub-gaps), splice the 2 sub-pairs
    in place of the gap, re-index the tail, recompute aggregates, rebuild artifacts.
    Returns the full updated pair list + result so the UI replaces its review."""
    st = _state.get(sid)
    if st is None:
        raise HTTPException(status_code=404, detail="Session not found (run a session first)")
    keys, eng, cfg, result = st["keys"], st["eng"], st["cfg"], st["result"]
    mid_engine = eng.rife_engine
    if not (0 <= index < len(keys) - 1):
        raise HTTPException(status_code=400, detail=f"gap index {index} out of range")

    data = await key.read()
    m = np.array(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.uint8)
    a, b = keys[index], keys[index + 1]

    # targeted re-fill: only the two new sub-gaps are gated/interpolated/QA'd
    sub = list(run_session([a, m, b], eng).pairs)   # [a->m, m->b]

    new_keys = keys[:index + 1] + [m] + keys[index + 1:]
    new_pairs: list = []
    for p in result.pairs:
        if p.index < index:
            new_pairs.append(p)
        elif p.index == index:
            sub[0].index = index
            if len(sub) > 1:
                sub[1].index = index + 1
            new_pairs.extend(sub)
        else:
            p.index += 1          # one key inserted -> tail shifts by one
            new_pairs.append(p)
    new_result = recompute_result(new_pairs)

    session_dir = _sessions[sid]

    # explainability + fractional defect boxes (same as the streaming worker)
    vlm_struct_fn = eng.vlm_struct_fn
    explanations = (explain_pairs(new_result, vlm_struct_fn=vlm_struct_fn,
                                  softness_fn=eng.softness_fn)
                    if vlm_struct_fn is not None else {})
    if explanations:
        H, W = new_keys[0].shape[:2]
        regions = {}
        for i, e in explanations.items():
            pb = region_box(e["region"], W, H)
            regions[i] = pb
            if pb and W and H:
                x0, y0, x1, y1 = pb
                e["box"] = [x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H]
    else:
        regions = {}

    ann_files = annotate_explained_pairs(new_result, explanations, session_dir)

    build_montage(new_result, new_keys, session_dir, regions=regions or None)
    build_report(new_result, session_dir)
    build_video(new_result, session_dir, fps=cfg.fps, factor=cfg.smoothness, mid_engine=mid_engine)
    pair_files = build_pair_frames(new_result, session_dir)

    st["keys"], st["result"] = new_keys, new_result
    st["rev"] = st.get("rev", 0) + 1
    bust = f"?r={st['rev']}"     # files are overwritten -> bust the browser cache by URL
    for i, fn in ann_files.items():
        explanations[i]["annotated_url"] = f"/session/{sid}/{fn}{bust}"
    pair_mids = {str(i): f"/session/{sid}/{fn}{bust}" for i, fn in pair_files.items()}
    artifact_urls = {
        "montage": f"/session/{sid}/montage.png{bust}",
        "report":  f"/session/{sid}/report.md{bust}",
        "video":   f"/session/{sid}/reconstructed.mp4{bust}",
    }

    pairs_payload = [
        PairEvent.from_pair(p, mid_url=pair_mids.get(str(p.index))).model_dump()
        for p in new_result.pairs
    ]
    result_payload = ResultEvent.from_result(new_result, artifact_urls,
                                             explanations=explanations,
                                             pair_mids=pair_mids,
                                             csq=eng.csq_calibrator).model_dump()
    return {"pairs": pairs_payload, "result": result_payload}
