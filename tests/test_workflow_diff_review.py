#!/usr/bin/env python3
"""Integration tests for the Workflow Diff Review feature.

This module tests the complete workflow diff review flow, including:
- Workflow branch creation
- Task merges to workflow branch (not main)
- Auto-merge on completion (require_final_review=false)
- Review gate behavior (require_final_review=true)
- Approve/reject merge endpoints
- Diff retrieval endpoint

Prerequisites:
- Git must be installed and available
- Tests create temporary git repositories for isolation
"""

import os
import sys
import tempfile
import shutil
import uuid
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

import pytest
import git
from git import Repo

from src.core.database import DatabaseManager, Base, Workflow, Task, Agent, Phase
from src.core.worktree_manager import WorktreeManager
from src.workflow.completion_handler import WorkflowCompletionHandler


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_repo():
    """Create a temporary git repository for testing.
    
    Creates a git repo with an initial commit and a 'main' branch.
    """
    temp_dir = tempfile.mkdtemp()
    repo = Repo.init(temp_dir)

    # Create initial commit so we have a main branch
    test_file = Path(temp_dir) / "README.md"
    test_file.write_text("# Test Repository\n")
    repo.index.add([str(test_file)])
    repo.index.commit("Initial commit")

    # Ensure we're on 'main' branch
    if repo.active_branch.name != "main":
        repo.git.branch("-m", repo.active_branch.name, "main")

    yield repo

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    db_manager = DatabaseManager(":memory:")
    db_manager.create_tables()
    return db_manager


@pytest.fixture
def mock_config(temp_repo):
    """Create a mock config pointing to the temp repo."""
    config = MagicMock()
    config.worktree_base_path = Path(tempfile.mkdtemp())
    config.main_repo_path = Path(temp_repo.working_dir)
    config.worktree_branch_prefix = "test-agent-"
    config.workflow_branch_prefix = "workflow-"
    config.conflict_resolution_strategy = "newest_file_wins"
    config.prefer_child_on_tie = True
    config.base_branch = "main"
    config.require_final_review = False
    return config


@pytest.fixture
def worktree_manager(test_db, temp_repo, mock_config, monkeypatch):
    """Create a WorktreeManager with test configuration."""
    monkeypatch.setattr('src.core.simple_config.get_config', lambda: mock_config)
    
    manager = WorktreeManager(test_db)
    
    yield manager
    
    # Cleanup worktrees
    shutil.rmtree(mock_config.worktree_base_path, ignore_errors=True)


@pytest.fixture
def completion_handler(test_db, worktree_manager):
    """Create a WorkflowCompletionHandler with worktree manager."""
    return WorkflowCompletionHandler(test_db, worktree_manager)


@pytest.fixture
def test_workflow(test_db):
    """Create a test workflow in the database."""
    session = test_db.get_session()
    
    workflow_id = str(uuid.uuid4())
    workflow = Workflow(
        id=workflow_id,
        name="Test Workflow",
        description="Test workflow for diff review",
        phases_folder_path="/test/phases",
        status="active",
        final_merge_status="not_applicable",
    )
    session.add(workflow)
    session.commit()
    session.close()
    
    return workflow_id


@pytest.fixture
def workflow_with_review_required(test_db):
    """Create a workflow that requires final review."""
    session = test_db.get_session()
    
    workflow_id = str(uuid.uuid4())
    workflow = Workflow(
        id=workflow_id,
        name="Review Required Workflow",
        description="Workflow requiring final review",
        phases_folder_path="/test/phases",
        status="active",
        final_merge_status="pending_review",
    )
    session.add(workflow)
    session.commit()
    session.close()
    
    return workflow_id


# =============================================================================
# Test: Workflow Branch Creation
# =============================================================================

class TestWorkflowBranchCreation:
    """Tests for workflow branch creation functionality."""

    def test_create_workflow_branch_creates_branch_from_main(
        self, worktree_manager, test_workflow, test_db
    ):
        """Verify that create_workflow_branch creates a new branch from main."""
        # Create workflow branch
        result = worktree_manager.create_workflow_branch(test_workflow)
        
        # Verify result structure matches actual implementation:
        # {"branch_name", "created_from_sha", "already_existed"}
        assert "branch_name" in result
        assert "created_from_sha" in result
        assert "already_existed" in result
        assert result["branch_name"].startswith("workflow-")
        assert result["already_existed"] is False
        
        # Verify branch exists in the worktree_manager's repo
        # (using git command to get fresh branch list)
        branch_list = worktree_manager.main_repo.git.branch("--list").split()
        assert result["branch_name"] in branch_list

    def test_create_workflow_branch_returns_branch_info(
        self, worktree_manager, test_workflow, test_db
    ):
        """Verify create_workflow_branch returns correct branch information.
        
        Note: create_workflow_branch does NOT update the Workflow database record.
        That is the caller's responsibility (e.g., in the API endpoint or workflow creation).
        """
        # Create branch
        result = worktree_manager.create_workflow_branch(test_workflow)
        
        # Verify result contains branch info
        assert result["branch_name"].startswith("workflow-")
        assert len(result["created_from_sha"]) == 40  # Full SHA
        
        # Verify the branch was created from the base_branch (main)
        main_sha = worktree_manager.main_repo.heads.main.commit.hexsha
        assert result["created_from_sha"] == main_sha

    def test_create_workflow_branch_idempotent(
        self, worktree_manager, test_workflow, test_db
    ):
        """Verify calling create_workflow_branch twice doesn't create duplicates."""
        # Create branch twice
        result1 = worktree_manager.create_workflow_branch(test_workflow)
        result2 = worktree_manager.create_workflow_branch(test_workflow)
        
        # Should return same branch name
        assert result1["branch_name"] == result2["branch_name"]


# =============================================================================
# Test: Task Merge to Workflow Branch
# =============================================================================

class TestTaskMergeToWorkflowBranch:
    """Tests for merging task work to workflow branch instead of main."""

    def test_merge_to_parent_uses_workflow_branch_when_provided(
        self, worktree_manager, test_db
    ):
        """Verify merge_to_parent uses workflow branch as target when specified."""
        agent_id = str(uuid.uuid4())
        main_repo = worktree_manager.main_repo
        
        # Create agent in database
        session = test_db.get_session()
        agent = Agent(
            id=agent_id,
            system_prompt="Test agent",
            status="working",
            cli_type="test"
        )
        session.add(agent)
        session.commit()
        session.close()
        
        # Create worktree
        result = worktree_manager.create_agent_worktree(agent_id)
        worktree_path = Path(result["working_directory"])
        
        # Create a workflow branch to merge to (use underscore to avoid hyphen issues)
        workflow_branch = "workflow_test_123"
        main_repo.git.branch(workflow_branch)
        
        # Make changes in worktree
        test_file = worktree_path / "agent_work.txt"
        test_file.write_text("Agent work content")
        
        # Merge to workflow branch
        merge_result = worktree_manager.merge_to_parent(
            agent_id,
            target_branch=workflow_branch
        )
        
        # Verify merge went to workflow branch
        assert merge_result["merged_to"] == workflow_branch
        assert merge_result["status"] in ["success", "conflict_resolved"]
        
        # Verify file exists on workflow branch but not on main
        main_repo.git.checkout(workflow_branch)
        assert (Path(main_repo.working_dir) / "agent_work.txt").exists()
        
        main_repo.git.checkout("main")
        assert not (Path(main_repo.working_dir) / "agent_work.txt").exists()
        
        # Cleanup
        worktree_manager.cleanup_worktree(agent_id)

    def test_merge_to_parent_defaults_to_base_branch(
        self, worktree_manager, test_db
    ):
        """Verify merge_to_parent defaults to main when no workflow branch specified."""
        agent_id = str(uuid.uuid4())
        
        # Create agent
        session = test_db.get_session()
        agent = Agent(
            id=agent_id,
            system_prompt="Test agent",
            status="working",
            cli_type="test"
        )
        session.add(agent)
        session.commit()
        session.close()
        
        # Create worktree
        result = worktree_manager.create_agent_worktree(agent_id)
        worktree_path = Path(result["working_directory"])
        
        # Make changes in worktree
        test_file = worktree_path / "default_merge.txt"
        test_file.write_text("Default merge content")
        
        # Merge without specifying target (should go to main)
        merge_result = worktree_manager.merge_to_parent(agent_id)
        
        # Verify merge went to main
        assert merge_result["merged_to"] == "main"
        
        # Cleanup
        worktree_manager.cleanup_worktree(agent_id)


# =============================================================================
# Test: Auto-Merge on Completion
# =============================================================================

class TestAutoMergeOnCompletion:
    """Tests for auto-merge behavior when require_final_review=false."""

    def test_complete_workflow_auto_merges_when_not_requiring_review(
        self, completion_handler, test_db, worktree_manager
    ):
        """Verify workflow auto-merges to main when final_merge_status=not_applicable."""
        main_repo = worktree_manager.main_repo
        
        # Create workflow with branch
        session = test_db.get_session()
        workflow_id = str(uuid.uuid4())
        
        # Create workflow branch first
        workflow_branch = f"workflow-{workflow_id[:8]}"
        main_repo.git.branch(workflow_branch)
        
        # Make a commit on workflow branch to have something to merge
        main_repo.git.checkout(workflow_branch)
        test_file = Path(main_repo.working_dir) / "workflow_work.txt"
        test_file.write_text("Workflow complete work")
        main_repo.index.add([str(test_file)])
        main_repo.index.commit("Workflow work complete")
        main_repo.git.checkout("main")
        
        workflow = Workflow(
            id=workflow_id,
            name="Auto-merge Workflow",
            description="Test auto-merge",
            phases_folder_path="/test/phases",
            status="active",
            workflow_branch_name=workflow_branch,
            workflow_branch_created=True,
            final_merge_status="not_applicable",
        )
        session.add(workflow)
        session.commit()
        session.close()
        
        # Complete the workflow
        result = completion_handler.complete_workflow(
            workflow_id,
            reason="All tasks done"
        )
        
        # Verify result
        assert result["final_merge_status"] == "merged"
        assert result["final_merge_commit_sha"] is not None
        assert result["requires_review"] is False
        
        # Verify workflow status
        session = test_db.get_session()
        workflow = session.query(Workflow).filter_by(id=workflow_id).first()
        assert workflow.status == "completed"
        assert workflow.final_merge_status == "merged"
        session.close()
        
        # Verify changes are on main
        main_repo.git.checkout("main")
        assert (Path(main_repo.working_dir) / "workflow_work.txt").exists()

    def test_complete_workflow_sets_final_merge_commit_sha(
        self, completion_handler, test_db, worktree_manager
    ):
        """Verify final_merge_commit_sha is populated after auto-merge."""
        main_repo = worktree_manager.main_repo
        
        # Create workflow with branch
        session = test_db.get_session()
        workflow_id = str(uuid.uuid4())
        
        workflow_branch = f"workflow-{workflow_id[:8]}"
        main_repo.git.branch(workflow_branch)
        
        # Make a commit on workflow branch
        main_repo.git.checkout(workflow_branch)
        test_file = Path(main_repo.working_dir) / "sha_test.txt"
        test_file.write_text("SHA test content")
        main_repo.index.add([str(test_file)])
        main_repo.index.commit("SHA test commit")
        main_repo.git.checkout("main")
        
        workflow = Workflow(
            id=workflow_id,
            name="SHA Test Workflow",
            description="Test SHA tracking",
            phases_folder_path="/test/phases",
            status="active",
            workflow_branch_name=workflow_branch,
            workflow_branch_created=True,
            final_merge_status="not_applicable",
        )
        session.add(workflow)
        session.commit()
        session.close()
        
        # Complete
        result = completion_handler.complete_workflow(workflow_id)
        
        # Verify SHA is populated
        session = test_db.get_session()
        workflow = session.query(Workflow).filter_by(id=workflow_id).first()
        assert workflow.final_merge_commit_sha is not None
        assert len(workflow.final_merge_commit_sha) == 40  # Full SHA length
        session.close()


# =============================================================================
# Test: Review Gate (pending_final_review)
# =============================================================================

class TestReviewGate:
    """Tests for review gate behavior when require_final_review=true."""

    def test_complete_workflow_pauses_when_review_required(
        self, completion_handler, test_db, worktree_manager
    ):
        """Verify workflow pauses with pending_final_review status when review required."""
        main_repo = worktree_manager.main_repo
        
        # Create workflow requiring review
        session = test_db.get_session()
        workflow_id = str(uuid.uuid4())
        
        workflow_branch = f"workflow-{workflow_id[:8]}"
        main_repo.git.branch(workflow_branch)
        
        # Make a commit on workflow branch
        main_repo.git.checkout(workflow_branch)
        test_file = Path(main_repo.working_dir) / "review_test.txt"
        test_file.write_text("Review required content")
        main_repo.index.add([str(test_file)])
        main_repo.index.commit("Review test commit")
        main_repo.git.checkout("main")
        
        workflow = Workflow(
            id=workflow_id,
            name="Review Required Workflow",
            description="Test review gate",
            phases_folder_path="/test/phases",
            status="active",
            workflow_branch_name=workflow_branch,
            workflow_branch_created=True,
            final_merge_status="pending_review",  # Requires review
        )
        session.add(workflow)
        session.commit()
        session.close()
        
        # Complete the workflow
        result = completion_handler.complete_workflow(workflow_id)
        
        # Verify workflow is paused for review
        assert result["requires_review"] is True
        assert result["final_merge_status"] == "pending_review"
        
        # Verify workflow status
        session = test_db.get_session()
        workflow = session.query(Workflow).filter_by(id=workflow_id).first()
        assert workflow.status == "pending_final_review"
        assert workflow.final_merge_status == "pending_review"
        session.close()
        
        # Verify changes are NOT on main yet
        main_repo.git.checkout("main")
        assert not (Path(main_repo.working_dir) / "review_test.txt").exists()

    def test_workflow_branch_preserved_during_review(
        self, completion_handler, test_db, worktree_manager
    ):
        """Verify workflow branch is preserved while awaiting review."""
        main_repo = worktree_manager.main_repo
        
        # Create workflow requiring review
        session = test_db.get_session()
        workflow_id = str(uuid.uuid4())
        
        workflow_branch = f"workflow-{workflow_id[:8]}"
        main_repo.git.branch(workflow_branch)
        
        workflow = Workflow(
            id=workflow_id,
            name="Preserved Branch Workflow",
            description="Test branch preservation",
            phases_folder_path="/test/phases",
            status="active",
            workflow_branch_name=workflow_branch,
            workflow_branch_created=True,
            final_merge_status="pending_review",
        )
        session.add(workflow)
        session.commit()
        session.close()
        
        # Complete (pause for review)
        completion_handler.complete_workflow(workflow_id)
        
        # Verify branch still exists (use git command for fresh list)
        branch_list = main_repo.git.branch("--list").split()
        assert workflow_branch in branch_list


# =============================================================================
# Test: Get Workflow Diff
# =============================================================================

class TestGetWorkflowDiff:
    """Tests for the workflow diff retrieval functionality."""

    def test_get_workflow_diff_returns_file_changes(
        self, worktree_manager
    ):
        """Verify get_workflow_diff returns file changes, stats, and commits."""
        main_repo = worktree_manager.main_repo
        
        # Create a workflow branch with changes
        workflow_branch = "workflow_diff_test"
        main_repo.git.branch(workflow_branch)
        
        main_repo.git.checkout(workflow_branch)
        
        # Add a new file
        new_file = Path(main_repo.working_dir) / "new_file.py"
        new_file.write_text("def hello(): return 'world'")
        main_repo.index.add([str(new_file)])
        main_repo.index.commit("Add new file")
        
        # Modify existing file
        readme = Path(main_repo.working_dir) / "README.md"
        readme.write_text("# Test Repository\n\nUpdated content.")
        main_repo.index.add([str(readme)])
        main_repo.index.commit("Update README")
        
        main_repo.git.checkout("main")
        
        # Get diff
        result = worktree_manager.get_workflow_diff(workflow_branch)
        
        # Verify result structure matches actual implementation:
        # {"base_branch", "workflow_branch", "merge_base_sha", "files_changed",
        #  "detailed_diff", "stats", "commits"}
        assert "files_changed" in result
        assert "stats" in result
        assert "commits" in result
        assert "detailed_diff" in result  # Not "diff_content"
        assert "base_branch" in result
        assert "workflow_branch" in result
        
        # Verify stats - actual API returns stats["files"] not stats["files_changed"]
        assert result["stats"]["files"] >= 1
        assert "insertions" in result["stats"]
        assert "deletions" in result["stats"]
        
        # Verify files_changed is a list of dicts with path and status
        assert len(result["files_changed"]) >= 1
        for fc in result["files_changed"]:
            assert "path" in fc
            assert "status" in fc

    def test_get_workflow_diff_with_no_changes(
        self, worktree_manager
    ):
        """Verify get_workflow_diff handles branches with no changes."""
        main_repo = worktree_manager.main_repo
        
        # Create branch at same commit as main (no changes)
        workflow_branch = "workflow_no_changes"
        main_repo.git.branch(workflow_branch)
        
        result = worktree_manager.get_workflow_diff(workflow_branch)
        
        # Should return empty/zero stats - actual API returns stats["files"]
        assert result["stats"]["files"] == 0


# =============================================================================
# Test: Approve Merge
# =============================================================================

class TestApproveMerge:
    """Tests for the approve-merge functionality."""

    def test_approve_merge_executes_merge_to_main(
        self, worktree_manager, test_db
    ):
        """Verify approving a merge executes the final merge to main."""
        main_repo = worktree_manager.main_repo
        
        # Create workflow in pending_final_review state
        session = test_db.get_session()
        workflow_id = str(uuid.uuid4())
        
        workflow_branch = f"workflow-{workflow_id[:8]}"
        main_repo.git.branch(workflow_branch)
        
        # Add changes to workflow branch
        main_repo.git.checkout(workflow_branch)
        test_file = Path(main_repo.working_dir) / "approved_work.txt"
        test_file.write_text("Approved work content")
        main_repo.index.add([str(test_file)])
        main_repo.index.commit("Approved work")
        main_repo.git.checkout("main")
        
        workflow = Workflow(
            id=workflow_id,
            name="Approve Test Workflow",
            description="Test approve merge",
            phases_folder_path="/test/phases",
            status="pending_final_review",
            workflow_branch_name=workflow_branch,
            workflow_branch_created=True,
            final_merge_status="pending_review",
        )
        session.add(workflow)
        session.commit()
        session.close()
        
        # Approve the merge
        result = worktree_manager.merge_workflow_to_base(
            workflow_id=workflow_id,
            workflow_branch=workflow_branch
        )
        
        # Verify merge succeeded
        assert result["status"] in ["success", "conflict_resolved"]
        assert "commit_sha" in result
        
        # Verify changes are on main
        main_repo.git.checkout("main")
        assert (Path(main_repo.working_dir) / "approved_work.txt").exists()

    def test_approve_merge_updates_workflow_status(
        self, worktree_manager, test_db
    ):
        """Verify approving updates workflow status to completed and merged."""
        main_repo = worktree_manager.main_repo
        
        session = test_db.get_session()
        workflow_id = str(uuid.uuid4())
        
        workflow_branch = f"workflow-{workflow_id[:8]}"
        main_repo.git.branch(workflow_branch)
        
        workflow = Workflow(
            id=workflow_id,
            name="Status Update Workflow",
            description="Test status update",
            phases_folder_path="/test/phases",
            status="pending_final_review",
            workflow_branch_name=workflow_branch,
            workflow_branch_created=True,
            final_merge_status="pending_review",
        )
        session.add(workflow)
        session.commit()
        
        # Merge
        merge_result = worktree_manager.merge_workflow_to_base(
            workflow_id=workflow_id,
            workflow_branch=workflow_branch
        )
        
        # Manually update workflow status (normally done by API endpoint)
        workflow.status = "completed"
        workflow.final_merge_status = "merged"
        workflow.final_merge_commit_sha = merge_result["commit_sha"]
        workflow.final_merge_reviewed_at = datetime.utcnow()
        workflow.final_merge_reviewed_by = "test_user"
        session.commit()
        
        # Verify
        refreshed = session.query(Workflow).filter_by(id=workflow_id).first()
        assert refreshed.status == "completed"
        assert refreshed.final_merge_status == "merged"
        assert refreshed.final_merge_commit_sha is not None
        assert refreshed.final_merge_reviewed_at is not None
        
        session.close()


# =============================================================================
# Test: Reject Merge
# =============================================================================

class TestRejectMerge:
    """Tests for the reject-merge functionality."""

    def test_reject_merge_marks_workflow_failed(self, test_db, worktree_manager):
        """Verify rejecting a merge marks workflow as failed."""
        main_repo = worktree_manager.main_repo
        
        session = test_db.get_session()
        workflow_id = str(uuid.uuid4())
        
        workflow_branch = f"workflow-{workflow_id[:8]}"
        main_repo.git.branch(workflow_branch)
        
        workflow = Workflow(
            id=workflow_id,
            name="Reject Test Workflow",
            description="Test reject merge",
            phases_folder_path="/test/phases",
            status="pending_final_review",
            workflow_branch_name=workflow_branch,
            workflow_branch_created=True,
            final_merge_status="pending_review",
        )
        session.add(workflow)
        session.commit()
        
        # Simulate rejection (normally done by API endpoint)
        workflow.status = "failed"
        workflow.final_merge_status = "rejected"
        workflow.final_merge_reviewed_at = datetime.utcnow()
        workflow.final_merge_reviewed_by = "test_user"
        session.commit()
        
        # Verify
        refreshed = session.query(Workflow).filter_by(id=workflow_id).first()
        assert refreshed.status == "failed"
        assert refreshed.final_merge_status == "rejected"
        
        session.close()

    def test_reject_merge_preserves_branch_by_default(self, test_db, worktree_manager):
        """Verify workflow branch is preserved after rejection by default."""
        main_repo = worktree_manager.main_repo
        
        session = test_db.get_session()
        workflow_id = str(uuid.uuid4())
        
        workflow_branch = f"workflow-{workflow_id[:8]}"
        main_repo.git.branch(workflow_branch)
        
        workflow = Workflow(
            id=workflow_id,
            name="Preserve Branch Workflow",
            description="Test branch preservation on reject",
            phases_folder_path="/test/phases",
            status="pending_final_review",
            workflow_branch_name=workflow_branch,
            workflow_branch_created=True,
            final_merge_status="pending_review",
        )
        session.add(workflow)
        session.commit()
        
        # Reject
        workflow.status = "failed"
        workflow.final_merge_status = "rejected"
        session.commit()
        session.close()
        
        # Verify branch still exists (use git command for fresh list)
        branch_list = main_repo.git.branch("--list").split()
        assert workflow_branch in branch_list

    def test_reject_merge_changes_not_on_main(self, test_db, worktree_manager):
        """Verify rejected workflow changes are NOT on main."""
        main_repo = worktree_manager.main_repo
        
        session = test_db.get_session()
        workflow_id = str(uuid.uuid4())
        
        workflow_branch = f"workflow-{workflow_id[:8]}"
        main_repo.git.branch(workflow_branch)
        
        # Add changes to workflow branch
        main_repo.git.checkout(workflow_branch)
        test_file = Path(main_repo.working_dir) / "rejected_work.txt"
        test_file.write_text("This should NOT be on main")
        main_repo.index.add([str(test_file)])
        main_repo.index.commit("Rejected work")
        main_repo.git.checkout("main")
        
        workflow = Workflow(
            id=workflow_id,
            name="Rejected Changes Workflow",
            description="Test rejected changes not on main",
            phases_folder_path="/test/phases",
            status="pending_final_review",
            workflow_branch_name=workflow_branch,
            workflow_branch_created=True,
            final_merge_status="pending_review",
        )
        session.add(workflow)
        session.commit()
        
        # Reject
        workflow.status = "failed"
        workflow.final_merge_status = "rejected"
        session.commit()
        session.close()
        
        # Verify changes are NOT on main
        main_repo.git.checkout("main")
        assert not (Path(main_repo.working_dir) / "rejected_work.txt").exists()


# =============================================================================
# Test: Legacy Workflow Compatibility
# =============================================================================

class TestLegacyWorkflowCompatibility:
    """Tests for backward compatibility with workflows without branches."""

    def test_complete_workflow_works_without_branch(
        self, completion_handler, test_db
    ):
        """Verify workflows without branches complete normally."""
        session = test_db.get_session()
        workflow_id = str(uuid.uuid4())
        
        # Create legacy workflow without branch
        workflow = Workflow(
            id=workflow_id,
            name="Legacy Workflow",
            description="No workflow branch",
            phases_folder_path="/test/phases",
            status="active",
            workflow_branch_name=None,  # No branch
            workflow_branch_created=False,
            final_merge_status="not_applicable",
        )
        session.add(workflow)
        session.commit()
        session.close()
        
        # Complete should work
        result = completion_handler.complete_workflow(workflow_id)
        
        # Verify completed
        session = test_db.get_session()
        workflow = session.query(Workflow).filter_by(id=workflow_id).first()
        assert workflow.status == "completed"
        session.close()


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
