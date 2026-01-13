"""Workflow deletion handler for permanently removing workflows and all associated data."""

import logging
from typing import Dict, Any, List
from datetime import datetime

from src.core.database import (
    DatabaseManager,
    Workflow,
    Phase,
    PhaseExecution,
    Task,
    Memory,
    AgentResult,
    AgentLog,
    ValidationReview,
    WorkflowResult,
    DiagnosticRun,
    Ticket,
    TicketComment,
    TicketHistory,
    TicketCommit,
    BoardConfig,
    Agent,
    AgentWorktree,
    WorktreeCommit,
    MergeConflictResolution,
    GuardianAnalysis,
    SteeringIntervention,
    DetectedDuplicate,
)
from src.agents.manager import AgentManager

logger = logging.getLogger(__name__)


class WorkflowActiveError(Exception):
    """Raised when attempting to delete an active workflow without force flag."""

    pass


class WorkflowDeletionHandler:
    """Handles permanent deletion of workflows and all associated data."""

    def __init__(self, db_manager: DatabaseManager, agent_manager: AgentManager):
        """Initialize the deletion handler.

        Args:
            db_manager: Database manager instance
            agent_manager: Agent manager for terminating agents
        """
        self.db_manager = db_manager
        self.agent_manager = agent_manager

    async def delete_workflow(
        self, workflow_id: str, force_terminate: bool = False
    ) -> Dict[str, Any]:
        """
        Permanently delete a workflow and all associated data.

        Args:
            workflow_id: ID of workflow to delete
            force_terminate: If True, terminate active agents first

        Returns:
            Deletion statistics (counts of deleted entities)

        Raises:
            ValueError: If workflow not found
            WorkflowActiveError: If workflow is active and force_terminate=False
        """
        logger.info(f"Starting deletion of workflow {workflow_id}")

        session = self.db_manager.get_session()
        deletion_stats = {
            "workflow_id": workflow_id,
            "deleted": {},
            "agents_terminated": 0,
            "deleted_at": datetime.utcnow().isoformat(),
        }

        try:
            # 1. Verify workflow exists
            workflow = session.query(Workflow).filter_by(id=workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow not found: {workflow_id}")

            # 2. Check if workflow is active
            if workflow.status == "active":
                if not force_terminate:
                    raise WorkflowActiveError(
                        f"Workflow {workflow_id} is active. Use force_terminate=True to proceed."
                    )
                # Terminate active agents first
                termination_result = await self._terminate_workflow_agents(
                    workflow_id, session
                )
                deletion_stats["agents_terminated"] = termination_result

            # 3. Delete in dependency order
            deletion_stats["deleted"] = self._cascade_delete(workflow_id, session)

            session.commit()
            logger.info(f"Successfully deleted workflow {workflow_id}")

            return deletion_stats

        except Exception as e:
            logger.error(f"Error during workflow deletion: {e}")
            session.rollback()
            raise
        finally:
            session.close()

    async def _terminate_workflow_agents(
        self, workflow_id: str, session
    ) -> int:
        """Terminate all active agents working on the workflow."""
        agents_terminated = 0

        # Find all active agents with tasks in this workflow
        agents = (
            session.query(Agent)
            .join(Task, Agent.id == Task.assigned_agent_id)
            .filter(
                Task.workflow_id == workflow_id,
                Agent.status.in_(["working", "idle"]),
            )
            .distinct()
            .all()
        )

        for agent in agents:
            try:
                logger.info(
                    f"Terminating agent {agent.id} for workflow deletion {workflow_id}"
                )
                await self.agent_manager.terminate_agent(agent.id)
                agents_terminated += 1
            except Exception as e:
                logger.error(f"Failed to terminate agent {agent.id}: {e}")

        return agents_terminated

    def _cascade_delete(self, workflow_id: str, session) -> Dict[str, int]:
        """Execute cascade deletion in correct order."""
        counts = {}

        # Get phase IDs for this workflow
        phase_ids = [
            p.id for p in session.query(Phase).filter_by(workflow_id=workflow_id).all()
        ]

        # Get task IDs and agent IDs for this workflow
        tasks = session.query(Task).filter_by(workflow_id=workflow_id).all()
        task_ids = [t.id for t in tasks]
        
        # Collect all agent IDs associated with this workflow
        agent_ids = list(
            set(
                [t.assigned_agent_id for t in tasks if t.assigned_agent_id]
                + [t.created_by_agent_id for t in tasks if t.created_by_agent_id]
            )
        )

        # Get ticket IDs for this workflow
        ticket_ids = [
            t.id for t in session.query(Ticket).filter_by(workflow_id=workflow_id).all()
        ]

        # 1. Delete PhaseExecutions (via phases)
        if phase_ids:
            counts["phase_executions"] = (
                session.query(PhaseExecution)
                .filter(PhaseExecution.phase_id.in_(phase_ids))
                .delete(synchronize_session=False)
            )
        else:
            counts["phase_executions"] = 0

        # 2. Delete Ticket children (Comments, History, Commits)
        if ticket_ids:
            counts["ticket_comments"] = (
                session.query(TicketComment)
                .filter(TicketComment.ticket_id.in_(ticket_ids))
                .delete(synchronize_session=False)
            )
            counts["ticket_history"] = (
                session.query(TicketHistory)
                .filter(TicketHistory.ticket_id.in_(ticket_ids))
                .delete(synchronize_session=False)
            )
            counts["ticket_commits"] = (
                session.query(TicketCommit)
                .filter(TicketCommit.ticket_id.in_(ticket_ids))
                .delete(synchronize_session=False)
            )
        else:
            counts["ticket_comments"] = 0
            counts["ticket_history"] = 0
            counts["ticket_commits"] = 0

        # 3. Delete Tickets
        counts["tickets"] = (
            session.query(Ticket)
            .filter_by(workflow_id=workflow_id)
            .delete(synchronize_session=False)
        )

        # 4. Delete Task children (Memories, AgentResults, ValidationReviews)
        if task_ids:
            counts["memories"] = (
                session.query(Memory)
                .filter(Memory.related_task_id.in_(task_ids))
                .delete(synchronize_session=False)
            )
            counts["agent_results"] = (
                session.query(AgentResult)
                .filter(AgentResult.task_id.in_(task_ids))
                .delete(synchronize_session=False)
            )
            counts["validation_reviews"] = (
                session.query(ValidationReview)
                .filter(ValidationReview.task_id.in_(task_ids))
                .delete(synchronize_session=False)
            )
        else:
            counts["memories"] = 0
            counts["agent_results"] = 0
            counts["validation_reviews"] = 0

        # 4b. Delete Agent children (all agent-related tables)
        if agent_ids:
            # Delete worktree commits first (FK to agent_worktrees)
            counts["worktree_commits"] = (
                session.query(WorktreeCommit)
                .filter(WorktreeCommit.agent_id.in_(agent_ids))
                .delete(synchronize_session=False)
            )
            # Delete merge conflict resolutions (FK to agent_worktrees)
            counts["merge_conflict_resolutions"] = (
                session.query(MergeConflictResolution)
                .filter(MergeConflictResolution.agent_id.in_(agent_ids))
                .delete(synchronize_session=False)
            )
            # Delete agent worktrees
            counts["agent_worktrees"] = (
                session.query(AgentWorktree)
                .filter(AgentWorktree.agent_id.in_(agent_ids))
                .delete(synchronize_session=False)
            )
            # Delete guardian analyses
            counts["guardian_analyses"] = (
                session.query(GuardianAnalysis)
                .filter(GuardianAnalysis.agent_id.in_(agent_ids))
                .delete(synchronize_session=False)
            )
            # Delete steering interventions
            counts["steering_interventions"] = (
                session.query(SteeringIntervention)
                .filter(SteeringIntervention.agent_id.in_(agent_ids))
                .delete(synchronize_session=False)
            )
            # Delete detected duplicates (has agent1_id and agent2_id)
            counts["detected_duplicates"] = (
                session.query(DetectedDuplicate)
                .filter(
                    (DetectedDuplicate.agent1_id.in_(agent_ids))
                    | (DetectedDuplicate.agent2_id.in_(agent_ids))
                )
                .delete(synchronize_session=False)
            )
            # Delete agent logs
            counts["agent_logs"] = (
                session.query(AgentLog)
                .filter(AgentLog.agent_id.in_(agent_ids))
                .delete(synchronize_session=False)
            )
            # Delete any remaining memories for these agents (not task-related)
            counts["agent_memories"] = (
                session.query(Memory)
                .filter(Memory.agent_id.in_(agent_ids))
                .delete(synchronize_session=False)
            )
        else:
            counts["worktree_commits"] = 0
            counts["merge_conflict_resolutions"] = 0
            counts["agent_worktrees"] = 0
            counts["guardian_analyses"] = 0
            counts["steering_interventions"] = 0
            counts["detected_duplicates"] = 0
            counts["agent_logs"] = 0
            counts["agent_memories"] = 0

        # 5. Delete Tasks (must clear agent FKs first)
        # Clear agent references before deleting tasks
        session.query(Task).filter_by(workflow_id=workflow_id).update(
            {"assigned_agent_id": None, "created_by_agent_id": None},
            synchronize_session=False,
        )
        counts["tasks"] = (
            session.query(Task)
            .filter_by(workflow_id=workflow_id)
            .delete(synchronize_session=False)
        )

        # 6. Delete WorkflowResults
        counts["workflow_results"] = (
            session.query(WorkflowResult)
            .filter_by(workflow_id=workflow_id)
            .delete(synchronize_session=False)
        )

        # 7. Delete DiagnosticRuns
        counts["diagnostic_runs"] = (
            session.query(DiagnosticRun)
            .filter_by(workflow_id=workflow_id)
            .delete(synchronize_session=False)
        )

        # 8. Delete BoardConfig (CASCADE should handle, but explicit for clarity)
        counts["board_config"] = (
            session.query(BoardConfig)
            .filter_by(workflow_id=workflow_id)
            .delete(synchronize_session=False)
        )

        # 9. Delete Phases
        counts["phases"] = (
            session.query(Phase)
            .filter_by(workflow_id=workflow_id)
            .delete(synchronize_session=False)
        )

        # 10. Delete Agents associated with this workflow
        if agent_ids:
            # Clear current_task_id references first to avoid FK constraint
            session.query(Agent).filter(Agent.id.in_(agent_ids)).update(
                {"current_task_id": None}, synchronize_session=False
            )
            counts["agents"] = (
                session.query(Agent)
                .filter(Agent.id.in_(agent_ids))
                .delete(synchronize_session=False)
            )
        else:
            counts["agents"] = 0

        # 11. Delete Workflow
        session.query(Workflow).filter_by(id=workflow_id).delete(
            synchronize_session=False
        )
        counts["workflow"] = 1

        return counts

    def get_deletion_preview(self, workflow_id: str) -> Dict[str, Any]:
        """Get a preview of what would be deleted without actually deleting."""
        session = self.db_manager.get_session()

        try:
            workflow = session.query(Workflow).filter_by(id=workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow not found: {workflow_id}")

            phase_ids = [
                p.id
                for p in session.query(Phase).filter_by(workflow_id=workflow_id).all()
            ]
            tasks = session.query(Task).filter_by(workflow_id=workflow_id).all()
            task_ids = [t.id for t in tasks]
            
            # Collect all agent IDs associated with this workflow
            agent_ids = list(
                set(
                    [t.assigned_agent_id for t in tasks if t.assigned_agent_id]
                    + [t.created_by_agent_id for t in tasks if t.created_by_agent_id]
                )
            )
            
            ticket_ids = [
                t.id
                for t in session.query(Ticket).filter_by(workflow_id=workflow_id).all()
            ]

            # Count active agents (subset of agent_ids that are still active)
            if agent_ids:
                active_agents = (
                    session.query(Agent)
                    .filter(
                        Agent.id.in_(agent_ids),
                        Agent.status.in_(["working", "idle"]),
                    )
                    .all()
                )
            else:
                active_agents = []

            # Build counts
            counts = {
                "phases": len(phase_ids),
                "tasks": len(task_ids),
                "tickets": len(ticket_ids),
                "agents": len(agent_ids),
            }

            # Count phase executions
            if phase_ids:
                counts["phase_executions"] = (
                    session.query(PhaseExecution)
                    .filter(PhaseExecution.phase_id.in_(phase_ids))
                    .count()
                )
            else:
                counts["phase_executions"] = 0

            # Count task-related entities
            if task_ids:
                counts["memories"] = (
                    session.query(Memory)
                    .filter(Memory.related_task_id.in_(task_ids))
                    .count()
                )
                counts["agent_results"] = (
                    session.query(AgentResult)
                    .filter(AgentResult.task_id.in_(task_ids))
                    .count()
                )
                counts["validation_reviews"] = (
                    session.query(ValidationReview)
                    .filter(ValidationReview.task_id.in_(task_ids))
                    .count()
                )
            else:
                counts["memories"] = 0
                counts["agent_results"] = 0
                counts["validation_reviews"] = 0

            # Count agent-related entities
            if agent_ids:
                counts["agent_logs"] = (
                    session.query(AgentLog)
                    .filter(AgentLog.agent_id.in_(agent_ids))
                    .count()
                )
                counts["agent_worktrees"] = (
                    session.query(AgentWorktree)
                    .filter(AgentWorktree.agent_id.in_(agent_ids))
                    .count()
                )
                counts["worktree_commits"] = (
                    session.query(WorktreeCommit)
                    .filter(WorktreeCommit.agent_id.in_(agent_ids))
                    .count()
                )
                counts["guardian_analyses"] = (
                    session.query(GuardianAnalysis)
                    .filter(GuardianAnalysis.agent_id.in_(agent_ids))
                    .count()
                )
                counts["steering_interventions"] = (
                    session.query(SteeringIntervention)
                    .filter(SteeringIntervention.agent_id.in_(agent_ids))
                    .count()
                )
            else:
                counts["agent_logs"] = 0
                counts["agent_worktrees"] = 0
                counts["worktree_commits"] = 0
                counts["guardian_analyses"] = 0
                counts["steering_interventions"] = 0

            # Count ticket-related entities
            if ticket_ids:
                counts["ticket_comments"] = (
                    session.query(TicketComment)
                    .filter(TicketComment.ticket_id.in_(ticket_ids))
                    .count()
                )
                counts["ticket_history"] = (
                    session.query(TicketHistory)
                    .filter(TicketHistory.ticket_id.in_(ticket_ids))
                    .count()
                )
                counts["ticket_commits"] = (
                    session.query(TicketCommit)
                    .filter(TicketCommit.ticket_id.in_(ticket_ids))
                    .count()
                )
            else:
                counts["ticket_comments"] = 0
                counts["ticket_history"] = 0
                counts["ticket_commits"] = 0

            # Count workflow results and diagnostic runs
            counts["workflow_results"] = (
                session.query(WorkflowResult)
                .filter_by(workflow_id=workflow_id)
                .count()
            )
            counts["diagnostic_runs"] = (
                session.query(DiagnosticRun)
                .filter_by(workflow_id=workflow_id)
                .count()
            )
            counts["board_config"] = (
                session.query(BoardConfig).filter_by(workflow_id=workflow_id).count()
            )

            return {
                "workflow_id": workflow_id,
                "workflow_name": workflow.name,
                "workflow_description": workflow.description,
                "workflow_status": workflow.status,
                "is_active": workflow.status == "active",
                "active_agents": [
                    {
                        "id": a.id,
                        "status": a.status,
                        "current_task_id": a.current_task_id,
                    }
                    for a in active_agents
                ],
                "counts": counts,
            }
        finally:
            session.close()
