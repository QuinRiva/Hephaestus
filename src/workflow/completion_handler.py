"""Workflow completion handler for marking workflows as complete."""

import logging
from typing import Dict, Any, Optional, TYPE_CHECKING

from datetime import datetime

from src.core.database import DatabaseManager, Workflow, Task, Phase, PhaseExecution, Agent
from src.core.simple_config import get_config
from src.services.incident_export_service import IncidentExportService

if TYPE_CHECKING:
    from src.core.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


class WorkflowNotReadyError(Exception):
    """Raised when workflow cannot be completed due to active work."""
    pass


class WorkflowCompletionHandler:
    """Handles manual and automatic completion of workflows."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        worktree_manager: Optional["WorktreeManager"] = None
    ):
        """Initialize the completion handler.

        Args:
            db_manager: Database manager instance
            worktree_manager: Optional worktree manager for git merge operations
        """
        self.db_manager = db_manager
        self.worktree_manager = worktree_manager

    def complete_workflow(self, workflow_id: str, reason: str = "Manual completion") -> Dict[str, Any]:
        """
        Mark a workflow as completed.

        This is used for:
        1. Manual completion from the UI when all tasks are done
        2. Auto-completion for has_result=False workflows

        Handles workflow branch merging based on final_merge_status:
        - "not_applicable": Auto-merge workflow branch to main on completion
        - "pending_review": Pause workflow with status "pending_final_review" for review
        - Legacy workflows without branch: Complete normally without merge

        Args:
            workflow_id: ID of the workflow to complete
            reason: Reason for completion (for logging)

        Returns:
            Dictionary with completion results including:
            - workflow_id, completed_at, reason, tasks_summary, phases_completed
            - final_merge_status: Current merge status
            - final_merge_commit_sha: Commit SHA if auto-merged
            - requires_review: True if workflow is paused for review

        Raises:
            ValueError: If workflow not found
            WorkflowNotReadyError: If workflow has active agents or pending tasks
        """
        logger.info(f"Completing workflow {workflow_id}: {reason}")

        session = self.db_manager.get_session()
        completion_result = {
            "workflow_id": workflow_id,
            "completed_at": datetime.utcnow().isoformat(),
            "reason": reason,
            "tasks_summary": {},
            "phases_completed": 0,
            "final_merge_status": None,
            "final_merge_commit_sha": None,
            "requires_review": False,
        }

        try:
            workflow = session.query(Workflow).filter_by(id=workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow not found: {workflow_id}")

            if workflow.status == "completed":
                logger.info(f"Workflow {workflow_id} already completed")
                return {
                    **completion_result,
                    "already_completed": True,
                    "completed_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
                    "final_merge_status": workflow.final_merge_status,
                    "final_merge_commit_sha": workflow.final_merge_commit_sha,
                }

            # Validate preconditions
            validation = self._validate_completion_preconditions(workflow_id, session)
            if not validation["can_complete"]:
                raise WorkflowNotReadyError(validation["reason"])

            # Get task summary before completing
            tasks = session.query(Task).filter_by(workflow_id=workflow_id).all()
            task_statuses = {}
            for task in tasks:
                task_statuses[task.status] = task_statuses.get(task.status, 0) + 1
            completion_result["tasks_summary"] = task_statuses

            # Complete any remaining phase executions
            phases_completed = self._complete_phase_executions(workflow_id, session)
            completion_result["phases_completed"] = phases_completed

            # Handle final merge based on workflow branch configuration
            merge_result = self._handle_final_merge(workflow, session)
            completion_result.update(merge_result)

            # If review is required, don't mark as completed yet
            if merge_result.get("requires_review"):
                logger.info(f"Workflow {workflow_id} paused for final review")
                session.commit()
                return completion_result

            # Mark workflow as completed (either no branch or auto-merge succeeded)
            workflow.status = "completed"
            workflow.completed_by_result = False  # Manual/auto completion, not result-based
            workflow.updated_at = datetime.utcnow()

            # Export incident memories if enabled
            config = get_config()
            if config.incident_logging_enabled:
                try:
                    export_result = IncidentExportService.export_all(
                        workflow_id=workflow_id,
                        output_dir=config.incident_logging_output_dir
                    )
                    logger.info(
                        f"Exported {export_result['total_incidents']} incidents to "
                        f"{export_result['readme_path']}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to export incidents (non-blocking): {e}")
            else:
                logger.debug("Incident logging disabled, skipping export")

            session.commit()
            logger.info(f"Successfully completed workflow {workflow_id}")

            return completion_result

        except (ValueError, WorkflowNotReadyError):
            session.rollback()
            raise
        except Exception as e:
            logger.error(f"Error completing workflow: {e}")
            session.rollback()
            raise
        finally:
            session.close()

    def _handle_final_merge(self, workflow: Workflow, session) -> Dict[str, Any]:
        """Handle the final merge of workflow branch to main based on configuration.

        Args:
            workflow: Workflow record
            session: Database session

        Returns:
            Dictionary with merge result:
            - final_merge_status: Current status after this operation
            - final_merge_commit_sha: Commit SHA if merged
            - requires_review: True if paused for review
            - merge_error: Error message if merge failed
        """
        result = {
            "final_merge_status": workflow.final_merge_status,
            "final_merge_commit_sha": workflow.final_merge_commit_sha,
            "requires_review": False,
            "merge_error": None,
        }

        # Check if workflow has a branch
        if not workflow.workflow_branch_name or not workflow.workflow_branch_created:
            # Legacy workflow without branch - proceed with normal completion
            logger.info(f"Workflow {workflow.id[:8]} has no branch, completing without merge")
            return result

        # Workflow has a branch - handle based on final_merge_status
        if workflow.final_merge_status == "pending_review":
            # Review is required - pause workflow
            logger.info(f"Workflow {workflow.id[:8]} requires final review, pausing")
            workflow.status = "pending_final_review"
            result["requires_review"] = True
            result["final_merge_status"] = "pending_review"
            return result

        if workflow.final_merge_status == "not_applicable":
            # Auto-merge mode - merge workflow branch to main
            logger.info(f"Workflow {workflow.id[:8]} auto-merge mode, merging branch to main")
            return self._execute_auto_merge(workflow, session)

        if workflow.final_merge_status in ("merged", "approved"):
            # Already merged or approved - nothing to do
            logger.info(f"Workflow {workflow.id[:8]} already in status {workflow.final_merge_status}")
            return result

        if workflow.final_merge_status == "rejected":
            # Workflow was rejected - complete without merge
            logger.info(f"Workflow {workflow.id[:8]} was rejected, completing without merge")
            return result

        # Unknown status - log warning and proceed with completion
        logger.warning(f"Workflow {workflow.id[:8]} has unknown final_merge_status: {workflow.final_merge_status}")
        return result

    def _execute_auto_merge(self, workflow: Workflow, session) -> Dict[str, Any]:
        """Execute automatic merge of workflow branch to main.

        Args:
            workflow: Workflow record
            session: Database session

        Returns:
            Dictionary with merge result
        """
        result = {
            "final_merge_status": workflow.final_merge_status,
            "final_merge_commit_sha": None,
            "requires_review": False,
            "merge_error": None,
        }

        if not self.worktree_manager:
            logger.error(f"Cannot auto-merge workflow {workflow.id[:8]}: worktree_manager not available")
            result["merge_error"] = "Worktree manager not available for merge operation"
            return result

        try:
            logger.info(f"[AUTO-MERGE] Merging workflow branch {workflow.workflow_branch_name} to main")

            merge_result = self.worktree_manager.merge_workflow_to_base(
                workflow_id=workflow.id,
                workflow_branch=workflow.workflow_branch_name
            )

            # Update workflow with merge result
            workflow.final_merge_status = "merged"
            workflow.final_merge_commit_sha = merge_result.get("commit_sha")

            result["final_merge_status"] = "merged"
            result["final_merge_commit_sha"] = merge_result.get("commit_sha")

            logger.info(
                f"[AUTO-MERGE] ✓ Workflow {workflow.id[:8]} merged successfully. "
                f"Commit: {merge_result.get('commit_sha', 'unknown')[:8]}"
            )

            return result

        except Exception as e:
            # Handle merge failure gracefully - don't crash the completion
            logger.error(f"[AUTO-MERGE] ✗ Failed to merge workflow {workflow.id[:8]}: {e}")
            result["merge_error"] = str(e)

            # Still mark as needing review so user can manually resolve
            workflow.final_merge_status = "pending_review"
            workflow.status = "pending_final_review"
            result["final_merge_status"] = "pending_review"
            result["requires_review"] = True

            logger.warning(
                f"[AUTO-MERGE] Workflow {workflow.id[:8]} moved to pending_final_review due to merge failure"
            )

            return result

    def _validate_completion_preconditions(self, workflow_id: str, session) -> Dict[str, Any]:
        """Validate that workflow can be safely completed.

        Args:
            workflow_id: Workflow ID to validate
            session: Database session

        Returns:
            Dictionary with can_complete bool and reason
        """
        # Check for active agents
        active_agents = session.query(Agent).join(
            Task, Agent.id == Task.assigned_agent_id
        ).filter(
            Task.workflow_id == workflow_id,
            Agent.status.in_(["working", "idle", "pending"])
        ).count()

        if active_agents > 0:
            return {
                "can_complete": False,
                "reason": f"Workflow has {active_agents} active agent(s). Wait for agents to finish or terminate them first.",
            }

        # Check for active tasks
        active_task_statuses = ["pending", "assigned", "in_progress", "under_review", "validation_in_progress"]
        active_tasks = session.query(Task).filter(
            Task.workflow_id == workflow_id,
            Task.status.in_(active_task_statuses)
        ).count()

        if active_tasks > 0:
            return {
                "can_complete": False,
                "reason": f"Workflow has {active_tasks} active task(s). Wait for tasks to complete or cancel them.",
            }

        return {"can_complete": True, "reason": None}

    def _complete_phase_executions(self, workflow_id: str, session) -> int:
        """Complete any in-progress phase executions.

        Args:
            workflow_id: Workflow ID
            session: Database session

        Returns:
            Number of phase executions completed
        """
        phases = session.query(Phase).filter_by(workflow_id=workflow_id).all()
        phase_ids = [p.id for p in phases]

        if not phase_ids:
            return 0

        phase_executions = session.query(PhaseExecution).filter(
            PhaseExecution.phase_id.in_(phase_ids),
            PhaseExecution.status.in_(["pending", "in_progress"])
        ).all()

        completed_count = 0
        for execution in phase_executions:
            execution.status = "completed"
            execution.completed_at = datetime.utcnow()
            execution.completion_summary = "Workflow manually completed"
            completed_count += 1
            logger.debug(f"Completed phase execution {execution.id}")

        return completed_count

    def get_completion_preview(self, workflow_id: str) -> Dict[str, Any]:
        """Get a preview of what completing the workflow would do.

        Args:
            workflow_id: Workflow ID

        Returns:
            Preview dictionary with workflow state and completion eligibility
        """
        session = self.db_manager.get_session()
        try:
            workflow = session.query(Workflow).filter_by(id=workflow_id).first()
            if not workflow:
                return {"error": "Workflow not found"}

            # Get task counts
            tasks = session.query(Task).filter_by(workflow_id=workflow_id).all()
            task_counts = {}
            for task in tasks:
                task_counts[task.status] = task_counts.get(task.status, 0) + 1

            # Check active agents
            active_agents = session.query(Agent).join(
                Task, Agent.id == Task.assigned_agent_id
            ).filter(
                Task.workflow_id == workflow_id,
                Agent.status.in_(["working", "idle", "pending"])
            ).count()

            # Check completion eligibility
            validation = self._validate_completion_preconditions(workflow_id, session)

            return {
                "workflow_id": workflow_id,
                "workflow_name": workflow.name,
                "workflow_status": workflow.status,
                "is_already_completed": workflow.status == "completed",
                "task_counts": task_counts,
                "total_tasks": len(tasks),
                "active_agents": active_agents,
                "can_complete": validation["can_complete"],
                "blocking_reason": validation["reason"],
            }

        finally:
            session.close()

    def check_auto_complete_eligibility(self, workflow_id: str) -> Dict[str, Any]:
        """Check if a workflow should be auto-completed.

        For workflows with has_result=False, this checks if:
        1. All tasks are in terminal states
        2. No agents are active
        3. No more phases to advance to

        Args:
            workflow_id: Workflow ID to check

        Returns:
            Dictionary with should_auto_complete bool and reason
        """
        session = self.db_manager.get_session()
        try:
            workflow = session.query(Workflow).filter_by(id=workflow_id).first()
            if not workflow:
                return {"should_auto_complete": False, "reason": "Workflow not found"}

            if workflow.status == "completed":
                return {"should_auto_complete": False, "reason": "Already completed"}

            # Get task counts
            tasks = session.query(Task).filter_by(workflow_id=workflow_id).all()
            if not tasks:
                return {"should_auto_complete": False, "reason": "No tasks in workflow"}

            # Check for active tasks
            active_statuses = ["pending", "assigned", "in_progress", "under_review", "validation_in_progress"]
            active_tasks = [t for t in tasks if t.status in active_statuses]
            if active_tasks:
                return {
                    "should_auto_complete": False,
                    "reason": f"{len(active_tasks)} tasks still active",
                }

            # Check for active agents
            active_agents = session.query(Agent).join(
                Task, Agent.id == Task.assigned_agent_id
            ).filter(
                Task.workflow_id == workflow_id,
                Agent.status.in_(["working", "idle", "pending"])
            ).count()

            if active_agents > 0:
                return {
                    "should_auto_complete": False,
                    "reason": f"{active_agents} agents still active",
                }

            # Check phases - are there remaining phases with no tasks?
            phases = session.query(Phase).filter_by(workflow_id=workflow_id).order_by(Phase.order).all()
            if phases:
                last_phase_with_tasks = None
                for phase in phases:
                    phase_tasks = [t for t in tasks if t.phase_id == phase.id]
                    if phase_tasks:
                        last_phase_with_tasks = phase

                if last_phase_with_tasks:
                    # Check if there are phases after the last one with tasks
                    remaining_phases = [p for p in phases if p.order > last_phase_with_tasks.order]
                    if remaining_phases:
                        # There are more phases but no tasks created for them
                        # This might be intentional (phase didn't create next phase tasks)
                        # So we still auto-complete
                        logger.debug(f"Workflow {workflow_id} has {len(remaining_phases)} unused phases, but all tasks done")

            # All conditions met - workflow should auto-complete
            done_count = len([t for t in tasks if t.status == "done"])
            failed_count = len([t for t in tasks if t.status == "failed"])

            return {
                "should_auto_complete": True,
                "reason": f"All {len(tasks)} tasks finished ({done_count} done, {failed_count} failed)",
                "tasks_done": done_count,
                "tasks_failed": failed_count,
                "total_tasks": len(tasks),
            }

        finally:
            session.close()
