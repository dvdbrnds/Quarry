"""
Execute alert scenarios as background asyncio tasks.

A scenario is a linear sequence of steps: send alerts, wait, clear.
Each running scenario is tracked by task_id so admins can monitor and abort.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from ..database import async_session

logger = logging.getLogger("quarry.scenario_runner")

_running: dict[str, dict] = {}


async def _execute_scenario(task_id: str, scenario, started_by: str):
    steps = scenario.steps or []
    last_alert_id = None

    for i, step in enumerate(steps):
        _running[task_id]["current_step"] = i + 1

        action = step.get("action") if isinstance(step, dict) else step.action
        delay = step.get("delay_seconds", 0) if isinstance(step, dict) else getattr(step, "delay_seconds", 0)

        if delay and delay > 0:
            await asyncio.sleep(delay)

        if action == "send_alert":
            template_id = step.get("template_id") if isinstance(step, dict) else step.template_id
            group_ids = step.get("group_ids") if isinstance(step, dict) else step.group_ids

            if not template_id:
                logger.warning("Scenario step %d: send_alert without template_id, skipping", i)
                continue

            async with async_session() as db:
                from ..models.alert_template import AlertTemplate
                from ..models.alert_log import AlertLog
                from .alert_dispatcher import dispatch_alert

                template = await db.get(AlertTemplate, uuid.UUID(str(template_id)))
                if not template:
                    logger.warning("Scenario step %d: template %s not found", i, template_id)
                    continue

                log_entry = AlertLog(
                    category=template.category,
                    subject=template.subject,
                    body_text=template.body_text,
                    body_sms=template.body_sms,
                    sent_by=started_by,
                    status="active",
                    target_group_ids=[str(g) for g in group_ids] if group_ids else None,
                )
                db.add(log_entry)
                await db.flush()
                await db.refresh(log_entry)

                await dispatch_alert(
                    log_entry.id, db,
                    group_ids=[uuid.UUID(str(g)) for g in group_ids] if group_ids else None,
                )
                last_alert_id = log_entry.id
                await db.commit()

                logger.info(
                    "Scenario %s step %d: sent alert %s (%s)",
                    task_id, i, log_entry.id, template.name,
                )

        elif action == "wait":
            pass

        elif action == "clear_previous":
            if last_alert_id:
                async with async_session() as db:
                    from .alert_dispatcher import clear_alert
                    await clear_alert(last_alert_id, started_by, db)
                    await db.commit()
                    logger.info("Scenario %s step %d: cleared alert %s", task_id, i, last_alert_id)
                last_alert_id = None

    logger.info("Scenario %s completed all %d steps", task_id, len(steps))


def run_scenario(scenario, started_by: str) -> str:
    task_id = str(uuid.uuid4())

    async def _wrapper():
        try:
            await _execute_scenario(task_id, scenario, started_by)
        except asyncio.CancelledError:
            logger.info("Scenario %s was aborted", task_id)
        except Exception as e:
            logger.error("Scenario %s failed: %s", task_id, e, exc_info=True)
        finally:
            _running.pop(task_id, None)

    task = asyncio.create_task(_wrapper())
    _running[task_id] = {
        "task": task,
        "scenario_id": str(scenario.id),
        "scenario_name": scenario.name,
        "current_step": 0,
        "total_steps": len(scenario.steps or []),
        "started_at": datetime.now(timezone.utc),
        "started_by": started_by,
    }
    return task_id


def get_running() -> list[dict]:
    result = []
    for tid, info in _running.items():
        result.append({
            "task_id": tid,
            "scenario_id": info["scenario_id"],
            "scenario_name": info["scenario_name"],
            "current_step": info["current_step"],
            "total_steps": info["total_steps"],
            "started_at": info["started_at"].isoformat(),
            "started_by": info["started_by"],
        })
    return result


def abort_scenario(task_id: str) -> bool:
    info = _running.get(task_id)
    if not info:
        return False
    info["task"].cancel()
    return True
