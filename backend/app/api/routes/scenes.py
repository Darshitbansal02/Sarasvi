from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database.engine import get_db_session
from app.models.scene_snapshot import SceneSnapshot
from app.models.session import Session
from pydantic import BaseModel, ConfigDict, Field
import uuid

router = APIRouter(prefix="/sessions/{session_id}/scenes", tags=["scenes"])


class SceneSnapshotCreate(BaseModel):
    concept_id: str | None = None
    schema_version: str = "1.0.0"
    runtime_version: str = "1.0.0"
    dsl_version: str = "1.0.0"
    pedagogical_state: dict
    pedagogical_plan: dict = Field(default_factory=dict)
    attention_state: dict
    transition_context: dict
    scene_graph_state: dict
    visual_plan: dict = Field(default_factory=dict)
    camera_state: dict
    transcript_state: dict
    semantic_summary: str | None = None
    replay_cursor: int
    timeline_offset: float
    
    model_config = ConfigDict(extra='ignore')


class SceneSnapshotResponse(SceneSnapshotCreate):
    id: str
    session_id: str

    model_config = ConfigDict(from_attributes=True)


@router.post("/", response_model=List[SceneSnapshotResponse])
async def sync_scene_snapshots(
    session_id: str,
    snapshots: List[SceneSnapshotCreate],
    db: AsyncSession = Depends(get_db_session)
):
    """
    Batched sync of compressed snapshots from the frontend.
    """
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    result = await db.execute(select(Session).filter(Session.id == session_uuid))
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")

    db_snapshots = []
    for s in snapshots:
        snapshot_obj = SceneSnapshot(
            session_id=session_uuid,
            concept_id=s.concept_id,
            schema_version=s.schema_version,
            runtime_version=s.runtime_version,
            dsl_version=s.dsl_version,
            pedagogical_state=s.pedagogical_state,
            pedagogical_plan=s.pedagogical_plan,
            attention_state=s.attention_state,
            transition_context=s.transition_context,
            scene_graph_state=s.scene_graph_state,
            visual_plan=s.visual_plan,
            camera_state=s.camera_state,
            transcript_state=s.transcript_state,
            semantic_summary=s.semantic_summary,
            replay_cursor=s.replay_cursor,
            timeline_offset=s.timeline_offset
        )
        db.add(snapshot_obj)
        db_snapshots.append(snapshot_obj)

    await db.commit()
    for s in db_snapshots:
        await db.refresh(s)

    # Convert UUIDs to strings for Pydantic
    return [
        SceneSnapshotResponse(
            **{k: v for k, v in s.__dict__.items() if not k.startswith('_')},
            id=str(s.id),
            session_id=str(s.session_id)
        ) for s in db_snapshots
    ]


@router.get("/", response_model=List[SceneSnapshotResponse])
async def get_scene_snapshots(
    session_id: str,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Restore state during a cold boot or cross-device resume.
    """
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    result = await db.execute(
        select(SceneSnapshot)
        .filter(SceneSnapshot.session_id == session_uuid)
        .order_by(SceneSnapshot.timeline_offset.asc())
    )
    snapshots = result.scalars().all()
    
    return [
        SceneSnapshotResponse(
            **{k: v for k, v in s.__dict__.items() if not k.startswith('_')},
            id=str(s.id),
            session_id=str(s.session_id)
        ) for s in snapshots
    ]
