"""
WebSocket Gateway — main WebSocket endpoint for Sarasvi.

Handles:
- Connection lifecycle
- NDJSON message routing
- Session binding
- Interruption triggering
- Heartbeat
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.database.engine import get_db_session
from app.events.event_protocol import TimelineEventData, EventType
from app.events.event_bus import get_event_bus
from app.events.event_store import EventStore
from app.events.generation_manager import GenerationManager
from app.events.branch_manager import BranchManager
from app.events.ndjson_stream import deserialize_line, serialize_dict_str
from app.websocket.connection_manager import get_connection_manager
from app.services.checkpoint_service import checkpoint_service
from app.services.session_finalizer import session_finalizer
from app.services.plan_exceptions import PlanRejectedError

logger = structlog.get_logger(__name__)

router = APIRouter()

from app.services.session_state_store import session_state_store


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    access_token: str | None = None,
):
    """Main WebSocket endpoint for realtime session communication."""
    import uuid
    from sqlalchemy import select
    from app.database.engine import get_session_factory
    from app.models.session import Session as SessionModel
    from app.api.deps import get_user_from_token

    # 1. Validate session_id is a valid UUID format
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        logger.warning("ws.connection_rejected", reason="invalid_uuid", session_id=session_id)
        await websocket.accept()
        await websocket.close(code=1008, reason="Invalid session ID format")
        return

    # 1b. Require an access token (query param, set by the frontend ws client).
    token = access_token or websocket.query_params.get("access_token")
    if not token:
        logger.warning("ws.connection_rejected", reason="missing_token", session_id=session_id)
        await websocket.accept()
        await websocket.close(code=1008, reason="Authentication required")
        return

    # 2. Validate token, confirm the session exists AND is owned by the token's user.
    factory = get_session_factory()
    try:
        async with factory() as db_session:
            user = await get_user_from_token(token, db_session)
            if user is None:
                await websocket.accept()
                await websocket.close(code=1008, reason="Invalid or expired token")
                logger.warning("ws.connection_rejected", reason="invalid_token", session_id=session_id)
                return
            session_obj = (
                await db_session.execute(
                    select(SessionModel).where(SessionModel.id == session_uuid)
                )
            ).scalar_one_or_none()
            
            if session_obj is not None and session_obj.user_id == user.id:
                if session_obj.status in ("created", "paused", "interrupted"):
                    session_obj.status = "active"
                    db_session.add(session_obj)
                    await db_session.commit()
    except Exception as e:
        logger.error("ws.connection_check_error", session_id=session_id, error=str(e))
        await websocket.accept()
        await websocket.close(code=1011, reason="Database connection error")
        return

    if session_obj is None:
        logger.warning("ws.connection_rejected", reason="session_not_found", session_id=session_id)
        await websocket.accept()
        await websocket.close(code=1008, reason="Session not found")
        return

    if session_obj.user_id != user.id:
        logger.warning("ws.connection_rejected", reason="not_owner", session_id=session_id, user_id=str(user.id))
        await websocket.accept()
        await websocket.close(code=1008, reason="Forbidden")
        return

    conn_manager = get_connection_manager()
    event_bus = get_event_bus()

    ws_id = await conn_manager.connect(websocket, session_id)
    managers = await session_state_store.get_managers(session_id)
    gen_manager: GenerationManager = managers["generation"]
    branch_manager: BranchManager = managers["branch"]

    logger.info("ws.session_started", session_id=session_id, ws_id=ws_id)

    # Send initial session state
    await websocket.send_text(
        serialize_dict_str(
            {
                "type": "session_init",
                "payload": {
                    "session_id": session_id,
                    "generation_id": gen_manager.current_generation_id,
                    "branch_id": branch_manager.active_branch_id,
                    "server_time_ms": int(
                        datetime.now(timezone.utc).timestamp() * 1000
                    ),
                },
            }
        )
    )

    # Buffer for micro-motion batching
    batch_queue = asyncio.Queue()

    # Subscribe to session events on the event bus
    async def forward_event(event: dict[str, Any]):
        """Forward events from event bus to WebSocket client."""
        # Only forward events for current generation
        event_gen = event.get("generation_id", "")
        if event_gen and gen_manager.is_stale(event_gen):
            logger.debug(
                "ws.stale_event_filtered",
                event_type=event.get("type"),
                generation_id=event_gen,
            )
            return
        await batch_queue.put(event)

    sub_id = await event_bus.subscribe(f"session:{session_id}", forward_event)

    async def batch_sender():
        """Batch and send events to reduce WebSocket overhead (runs ~60Hz)."""
        while True:
            events = []
            try:
                event = await asyncio.wait_for(batch_queue.get(), timeout=1.0)
                events.append(event)
                while not batch_queue.empty():
                    events.append(batch_queue.get_nowait())
                
                # Check if WebSocket is still connected before sending
                if websocket.client_state.name != "CONNECTED":
                    logger.debug("ws.batch_sender_stopping", reason="client_disconnected")
                    break
                
                await conn_manager.send_event_batch(session_id, events)
                await asyncio.sleep(0.016)  # ~60fps flush rate
            except asyncio.TimeoutError:
                # No events in queue, just loop and check again
                if websocket.client_state.name != "CONNECTED":
                    break
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("ws.batch_send_error", error=str(e))
                # If the WebSocket is dead, stop the sender
                if websocket.client_state.name != "CONNECTED":
                    break

    batch_sender_task = asyncio.create_task(batch_sender(), name=f"batch_sender_{session_id}")

    # Persistence Listener: persist every event to the DB OFF the delivery path.
    # We use a batch queue and a single worker task to pull events, batch them,
    # and write them to SQLite in a single transaction. This prevents SQLite lock contention
    # and avoids blocking the asyncio event loop under high bursts (e.g. 135+ events).
    persist_queue = asyncio.Queue()

    async def persist_worker():
        """Batch persist events to database in a single transaction."""
        while True:
            try:
                # Wait for at least one event
                event = await persist_queue.get()
                batch = [event]
                
                # Consume as many events as we can immediately (up to 50 events or 50ms elapsed)
                start_time = asyncio.get_event_loop().time()
                while len(batch) < 50 and not persist_queue.empty():
                    batch.append(persist_queue.get_nowait())
                    if asyncio.get_event_loop().time() - start_time > 0.05: # 50ms batching window
                        break

                from app.events.event_protocol import TimelineEventData
                from app.database.engine import get_session_factory
                
                factory = get_session_factory()
                max_retries = 3
                retry_delay = 0.1
                
                for attempt in range(max_retries):
                    try:
                        async with factory() as task_db:
                            task_store = EventStore(task_db)
                            for evt in batch:
                                try:
                                    if "event_id" not in evt:
                                        evt["event_id"] = str(uuid.uuid4())
                                    if "version_id" not in evt:
                                        evt["version_id"] = "1"
                                    if "start_ms" not in evt:
                                        evt["start_ms"] = 0
                                        
                                    data = TimelineEventData(**evt)
                                    await task_store.persist_event(
                                        data, uuid.UUID(session_id) if isinstance(session_id, str) else session_id
                                    )
                                except Exception as e:
                                    logger.error("ws.persistence_parse_error", event_type=evt.get("type"), error=str(e))
                            await task_db.commit()
                        break  # commit succeeded, break the retry loop
                    except Exception as e:
                        if attempt < max_retries - 1:
                            backoff = retry_delay * (2 ** attempt)
                            logger.warning("ws.persistence_commit_retry", attempt=attempt+1, error=str(e), backoff_ms=int(backoff * 1000))
                            await asyncio.sleep(backoff)
                        else:
                            logger.error("ws.persistence_commit_failed_all_attempts", error=str(e))
                            raise e
                
                for _ in range(len(batch)):
                    persist_queue.task_done()
                    
            except asyncio.CancelledError:
                # If cancelled, try to persist any remaining items in the queue in one final batch
                remaining = []
                while not persist_queue.empty():
                    remaining.append(persist_queue.get_nowait())
                if remaining:
                    try:
                        from app.events.event_protocol import TimelineEventData
                        from app.database.engine import get_session_factory
                        
                        factory = get_session_factory()
                        for attempt in range(2):
                            try:
                                async with factory() as task_db:
                                    task_store = EventStore(task_db)
                                    for evt in remaining:
                                        if "event_id" not in evt:
                                            evt["event_id"] = str(uuid.uuid4())
                                        if "version_id" not in evt:
                                            evt["version_id"] = "1"
                                        if "start_ms" not in evt:
                                            evt["start_ms"] = 0
                                            
                                        data = TimelineEventData(**evt)
                                        await task_store.persist_event(
                                            data, uuid.UUID(session_id) if isinstance(session_id, str) else session_id
                                        )
                                    await task_db.commit()
                                break
                            except Exception as e:
                                if attempt == 0:
                                    logger.warning("ws.persistence_final_commit_retry", error=str(e))
                                    await asyncio.sleep(0.05)
                                else:
                                    logger.error("ws.persistence_final_error", error=str(e))
                    finally:
                        for _ in range(len(remaining)):
                            persist_queue.task_done()
                break
            except Exception as e:
                logger.error("ws.persistence_worker_error", error=str(e))
                await asyncio.sleep(1.0)

    persist_worker_task = asyncio.create_task(persist_worker(), name=f"persist_worker_{session_id}")

    async def persist_to_db(event: dict[str, Any]):
        await persist_queue.put(dict(event))

    persistence_sub_id = await event_bus.subscribe(f"session:{session_id}", persist_to_db)

    # Heartbeat task
    async def heartbeat():
        while True:
            try:
                await asyncio.sleep(30)
                await websocket.send_text(
                    serialize_dict_str(
                        {
                            "type": "heartbeat",
                            "payload": {
                                "server_time_ms": int(
                                    datetime.now(timezone.utc).timestamp() * 1000
                                ),
                                "generation_id": gen_manager.current_generation_id,
                            },
                        }
                    )
                )
            except Exception:
                break

    heartbeat_task = asyncio.create_task(heartbeat(), name=f"heartbeat_{session_id}")

    try:
        while True:
            # Receive NDJSON messages from client
            raw_message = await websocket.receive_text()

            try:
                message = deserialize_line(raw_message)
            except Exception as e:
                logger.warning("ws.invalid_message", error=str(e))
                await websocket.send_text(
                    serialize_dict_str(
                        {
                            "type": "error",
                            "payload": {"message": f"Invalid NDJSON: {e}"},
                        }
                    )
                )
                continue

            msg_type = message.get("type", "")

            # ── Handle different message types ───────────────────
            if msg_type == "student_message":
                # Route through the SINGLE authoritative pipeline — the same
                # _run_llm_teaching_logic used by REST /teach. It publishes events
                # straight to the session event bus, which this socket forwards.
                # Run as a background task with its OWN db session so the long-lived
                # stream never blocks the receive loop (interrupts must stay live)
                # and never races the persistence subscriber on the connection-scoped
                # session (AsyncSession is not concurrency-safe).
                #
                # CRITICAL: the student's typed text is a QUESTION/DOUBT — not a new
                # lesson topic. We preserve the session's original topic and pass the
                # student text as student_question so the LLM pivots around that
                # specific doubt rather than launching an entirely new lesson.
                student_question_text = message.get("payload", {}).get("text", "")
                confusion = message.get("payload", {}).get("confusion_level", 0.0)
                generation_id = gen_manager.current_generation_id

                async def _run_student_message(student_question_text: str, confusion: float, generation_id: str):
                    from sqlalchemy import select
                    from app.database.engine import get_session_factory
                    from app.models.session import Session as SessionModel
                    from app.api.routes.sessions import _run_llm_teaching_logic

                    factory = get_session_factory()
                    async with factory() as task_db:
                        try:
                            sess_row = (await task_db.execute(
                                select(SessionModel).where(SessionModel.id == uuid.UUID(session_id))
                            )).scalar_one_or_none()
                            if sess_row is not None:
                                # Use the original lesson topic; pivot around the student's question
                                await _run_llm_teaching_logic(
                                    session_id=uuid.UUID(session_id),
                                    user_id=sess_row.user_id,
                                    generation_id=generation_id,
                                    topic=sess_row.topic,  # original lesson topic, not student text
                                    confusion_level=confusion,
                                    is_pivot=True,
                                    student_question=student_question_text,
                                )

                        except PlanRejectedError as plan_err:
                            logger.error("ws.plan_rejected", error=str(plan_err), student_question=student_question_text)
                        except Exception as gen_err:
                            logger.error("ws.generation_error", error=str(gen_err), student_question=student_question_text)

                # Submit through the job manager so it's cancellable and tracked.
                from app.services.generation_job_manager import generation_job_manager
                await generation_job_manager.cancel_and_wait(session_id)
                generation_job_manager.submit(
                    session_id,
                    _run_student_message(student_question_text, confusion, generation_id),
                    generation_id=generation_id,
                )

            elif msg_type == "interrupt":
                # STOP_AND_REPLAN — core interruption handling
                from app.services.generation_job_manager import generation_job_manager
                await generation_job_manager.cancel_and_wait(session_id)
                old_gen, new_gen = gen_manager.invalidate_current()

                # Create a new branch
                branch = branch_manager.create_branch(
                    branch_point_sequence=gen_manager.current_sequence,
                    reason="interruption",
                )

                # Persist the generation/branch transition durably.
                await session_state_store.save_managers(session_id)

                # Flush the event bus channel
                await event_bus.flush_channel(f"session:{session_id}")

                # Notify client of interruption
                await conn_manager.send_event(
                    session_id,
                    {
                        "type": "interruption",
                        "payload": {
                            "previous_generation_id": old_gen,
                            "new_generation_id": new_gen,
                            "new_branch_id": branch.branch_id,
                            "reason": message.get("payload", {}).get(
                                "reason", "user_text"
                            ),
                            "message": message.get("payload", {}).get(
                                "message", ""
                            ),
                        },
                        "generation_id": new_gen,
                        "branch_id": branch.branch_id,
                        "sequence_number": gen_manager.next_sequence(),
                        "server_timestamp": int(
                            datetime.now(timezone.utc).timestamp() * 1000
                        ),
                    },
                )

                logger.info(
                    "ws.interruption_handled",
                    session_id=session_id,
                    old_gen=old_gen,
                    new_gen=new_gen,
                    new_branch=branch.branch_id,
                )

            elif msg_type == "checkpoint_response":
                # Student answered a Socratic checkpoint question. Evaluate via the
                # graph-free CheckpointService (updates the live student model).
                response_text = message.get("payload", {}).get("text", "")
                question_text = message.get("payload", {}).get("question", "")
                try:
                    result = await checkpoint_service.evaluate(
                        session_id, response_text, question_text
                    )
                except Exception as eval_err:
                    logger.error("ws.checkpoint_eval_error", error=str(eval_err))
                    await websocket.send_text(
                        serialize_dict_str({"type": "error", "payload": {"message": f"Evaluation error: {eval_err}"}})
                    )
                    continue

                followup_events = result.get("events", [])
                for event in followup_events:
                    event.update({
                        "generation_id": gen_manager.current_generation_id,
                        "branch_id": branch_manager.active_branch_id,
                        "sequence_number": gen_manager.next_sequence(),
                        "server_timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                    })
                    await event_bus.publish(f"session:{session_id}", event)

                logger.info(
                    "ws.checkpoint_response_handled",
                    session_id=session_id,
                    is_correct=result.get("is_correct"),
                    followup_events=len(followup_events),
                )

            elif msg_type == "request_replay":
                # Client requested session replay
                await event_bus.publish(
                    f"session:{session_id}",
                    {
                        "type": "replay_requested",
                        "payload": message.get("payload", {}),
                    },
                )

            elif msg_type == "ping":
                await websocket.send_text(
                    serialize_dict_str(
                        {
                            "type": "pong",
                            "payload": {
                                "client_time_ms": message.get("payload", {}).get(
                                    "client_time_ms", 0
                                ),
                                "server_time_ms": int(
                                    datetime.now(timezone.utc).timestamp() * 1000
                                ),
                            },
                        }
                    )
                )

            elif msg_type == "clock_sync_request":
                await websocket.send_text(
                    serialize_dict_str(
                        {
                            "type": "clock_sync_response",
                            "client_time": message.get("client_time")
                            or message.get("payload", {}).get("client_time"),
                            "server_time": int(
                                datetime.now(timezone.utc).timestamp() * 1000
                            ),
                        }
                    )
                )

    except WebSocketDisconnect:
        logger.info("ws.disconnected", session_id=session_id, ws_id=ws_id)
    except Exception as e:
        logger.error("ws.error", session_id=session_id, error=str(e), exc_info=True)
    finally:
        # 1. Cancel tasks
        for task in [heartbeat_task, batch_sender_task]:
            try:
                task.cancel()
            except Exception as e:
                logger.error("ws.cleanup.cancel_task_error", task=task.get_name(), error=str(e))

        # 2. Drain and cancel persistence worker
        try:
            if not persist_queue.empty():
                await asyncio.wait_for(persist_queue.join(), timeout=2.0)
        except Exception as e:
            logger.warning("ws.persistence_drain_timeout", error=str(e))
        finally:
            persist_worker_task.cancel()
            try:
                await persist_worker_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("ws.cleanup.persist_worker_error", error=str(e))

        # 3. Unsubscribe from event bus (independent try-excepts)
        try:
            await event_bus.unsubscribe(sub_id)
        except Exception as e:
            logger.error("ws.cleanup.unsubscribe_error", sub_id=sub_id, error=str(e))

        try:
            await event_bus.unsubscribe(persistence_sub_id)
        except Exception as e:
            logger.error("ws.cleanup.unsubscribe_error", sub_id=persistence_sub_id, error=str(e))

        # 4. Disconnect from connection manager
        try:
            await conn_manager.disconnect(websocket)
        except Exception as e:
            logger.error("ws.cleanup.disconnect_error", error=str(e))

        # 5. Cleanup session managers and trigger finalization if no more connections
        try:
            if conn_manager.get_session_connection_count(session_id) == 0:
                await session_finalizer.finalize(session_id)
                # Persist final generation/branch state, then drop the in-process cache.
                await session_state_store.save_managers(session_id)
                session_state_store.evict(session_id)
                logger.info("ws.session_cleanup", session_id=session_id)
        except Exception as e:
            logger.error("ws.cleanup.session_finalize_error", session_id=session_id, error=str(e))
