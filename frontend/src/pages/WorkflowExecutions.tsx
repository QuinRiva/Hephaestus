import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWorkflow } from '@/context/WorkflowContext';
import { useQuery } from '@tanstack/react-query';
import { apiService } from '@/services/api';
import { WorkflowExecution } from '@/types';
import { motion, AnimatePresence } from 'framer-motion';
import { Workflow, ExternalLink, X, Layers, ListTodo, Rocket, Trash2, CheckCircle, GitMerge, Eye } from 'lucide-react';
import StatusBadge from '@/components/StatusBadge';
import TaskDetailModal from '@/components/TaskDetailModal';
import LaunchWorkflowModal from '@/components/LaunchWorkflowModal';
import DeleteWorkflowDialog from '@/components/DeleteWorkflowDialog';
import FinalDiffReviewModal from '@/components/FinalDiffReviewModal';

// Helper function
const formatDuration = (startTime: string) => {
  const start = new Date(startTime);
  const now = new Date();
  const diffMs = now.getTime() - start.getTime();
  const hours = Math.floor(diffMs / (1000 * 60 * 60));
  const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
};

// Workflow Detail Modal
const WorkflowDetailModal: React.FC<{
  execution: WorkflowExecution;
  onClose: () => void;
}> = ({ execution, onClose }) => {
  const navigate = useNavigate();
  const { selectExecution } = useWorkflow();
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  // Fetch detailed execution info with phases
  const { data: details } = useQuery({
    queryKey: ['workflow-execution-detail', execution.id],
    queryFn: () => apiService.getWorkflowExecution(execution.id),
    refetchInterval: 5000,
  });

  // Fetch tasks for this workflow
  const { data: tasksResponse } = useQuery({
    queryKey: ['workflow-tasks', execution.id],
    queryFn: () => apiService.getTasks(0, 50, undefined, execution.id),
    refetchInterval: 5000,
  });

  const handleGoToOverview = () => {
    selectExecution(execution.id);
    navigate('/overview');
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="bg-white rounded-lg shadow-xl p-6 w-full max-w-2xl max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex justify-between items-start mb-4">
          <div>
            <h2 className="text-xl font-bold text-gray-800">{execution.description || execution.definition_name}</h2>
            <p className="text-sm text-gray-500">{execution.definition_name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Status and Stats */}
        <div className="grid grid-cols-4 gap-3 mb-4">
          <div className="bg-gray-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-gray-800">{execution.stats?.total_tasks || 0}</div>
            <div className="text-xs text-gray-500">Total Tasks</div>
          </div>
          <div className="bg-green-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-green-600">{execution.stats?.done_tasks || 0}</div>
            <div className="text-xs text-gray-500">Completed</div>
          </div>
          <div className="bg-blue-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-blue-600">{execution.stats?.active_tasks || 0}</div>
            <div className="text-xs text-gray-500">Active</div>
          </div>
          <div className="bg-red-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-red-600">{execution.stats?.failed_tasks || 0}</div>
            <div className="text-xs text-gray-500">Failed</div>
          </div>
        </div>

        {/* Phases Summary */}
        {details?.phases && details.phases.length > 0 && (
          <div className="mb-4">
            <div className="flex justify-between items-center mb-2">
              <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <Layers className="w-4 h-4" />
                Phases ({details.phases.length})
              </h3>
              <button
                onClick={() => {
                  selectExecution(execution.id);
                  navigate('/phases');
                  onClose();
                }}
                className="text-xs text-blue-600 hover:text-blue-800"
              >
                View Details →
              </button>
            </div>
            <div className="flex gap-2">
              {details.phases.map((phase: any) => (
                <div key={phase.id} className="flex-1 bg-gray-50 rounded-lg p-2 text-center">
                  <div className="text-xs font-medium text-gray-700">P{phase.order}</div>
                  <div className="text-lg font-bold text-gray-800">{phase.completed_tasks}/{phase.total_tasks}</div>
                  <div className="text-[10px] text-gray-500">{phase.name.substring(0, 10)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tasks List */}
        {tasksResponse && Array.isArray(tasksResponse) && tasksResponse.length > 0 && (
          <div className="mb-4">
            <div className="flex justify-between items-center mb-2">
              <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <ListTodo className="w-4 h-4" />
                Tasks ({tasksResponse.length})
              </h3>
              <button
                onClick={() => {
                  selectExecution(execution.id);
                  navigate('/tasks');
                  onClose();
                }}
                className="text-xs text-blue-600 hover:text-blue-800"
              >
                View All →
              </button>
            </div>
            <div className="max-h-48 overflow-y-auto space-y-2 pr-1">
              {tasksResponse.map((task: any) => (
                <div
                  key={task.id}
                  onClick={() => setSelectedTaskId(task.id)}
                  className="bg-gray-50 rounded-lg p-2 flex items-center justify-between hover:bg-blue-50 hover:border-blue-200 border border-transparent transition-colors cursor-pointer"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-gray-800 truncate">
                      {task.enriched_description || task.raw_description || task.description}
                    </div>
                    <div className="text-xs text-gray-500 flex items-center gap-2 mt-0.5">
                      <span>P{task.phase_id}</span>
                      <span>•</span>
                      <span className="capitalize">{task.priority}</span>
                    </div>
                  </div>
                  <div className="ml-2 flex-shrink-0">
                    <StatusBadge status={task.status} size="sm" />
                  </div>
                </div>
              ))}
            </div>

            {/* Task Detail Modal */}
            {selectedTaskId && (
              <TaskDetailModal
                taskId={selectedTaskId}
                onClose={() => setSelectedTaskId(null)}
                onNavigateToTask={(taskId) => {
                  setSelectedTaskId(taskId);
                }}
              />
            )}
          </div>
        )}

        {/* Info */}
        <div className="text-xs text-gray-500 mb-4">
          <div>Started: {new Date(execution.created_at).toLocaleString()}</div>
          <div>Duration: {formatDuration(execution.created_at)}</div>
          {execution.working_directory && <div>Working Dir: {execution.working_directory}</div>}
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded-lg transition-colors"
          >
            Close
          </button>
          <button
            onClick={handleGoToOverview}
            className="flex-1 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition-colors"
          >
            Go to Overview
          </button>
        </div>
      </motion.div>
    </div>
  );
};

// Complete Workflow Dialog Component
const CompleteWorkflowDialog: React.FC<{
  open: boolean;
  workflowId: string | null;
  workflowName: string | undefined;
  onClose: () => void;
  onCompleted: () => void;
}> = ({ open, workflowId, workflowName, onClose, onCompleted }) => {
  const [isCompleting, setIsCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch completion preview
  const { data: preview, isLoading: previewLoading } = useQuery({
    queryKey: ['workflow-completion-preview', workflowId],
    queryFn: () => workflowId ? apiService.getWorkflowCompletionPreview(workflowId) : null,
    enabled: open && !!workflowId,
  });

  const handleComplete = async () => {
    if (!workflowId) return;

    setIsCompleting(true);
    setError(null);

    try {
      await apiService.completeWorkflowExecution(workflowId);
      onCompleted();
      onClose();
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to complete workflow');
    } finally {
      setIsCompleting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-green-100 rounded-full">
            <CheckCircle className="w-6 h-6 text-green-600" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-gray-800">Mark Workflow Complete</h2>
            <p className="text-sm text-gray-500">{workflowName}</p>
          </div>
        </div>

        {previewLoading ? (
          <div className="flex justify-center py-6">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-green-600"></div>
          </div>
        ) : preview ? (
          <div className="space-y-4">
            {!preview.can_complete && (
              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                <p className="text-sm text-yellow-800">
                  <strong>Cannot complete:</strong> {preview.reason}
                </p>
              </div>
            )}

            <div className="bg-gray-50 rounded-lg p-3 space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Total Tasks</span>
                <span className="font-medium">{preview.total_tasks}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Completed Tasks</span>
                <span className="font-medium text-green-600">{preview.completed_tasks}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Pending Tasks</span>
                <span className={`font-medium ${preview.pending_tasks > 0 ? 'text-yellow-600' : ''}`}>
                  {preview.pending_tasks}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Active Agents</span>
                <span className={`font-medium ${preview.active_agents > 0 ? 'text-yellow-600' : ''}`}>
                  {preview.active_agents}
                </span>
              </div>
            </div>

            {preview.can_complete && (
              <p className="text-sm text-gray-600">
                This will mark the workflow as completed and finalize all phase executions.
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-gray-500">Loading workflow information...</p>
        )}

        {error && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors"
            disabled={isCompleting}
          >
            Cancel
          </button>
          <button
            onClick={handleComplete}
            disabled={isCompleting || !preview?.can_complete}
            className={`flex-1 px-4 py-2 rounded-lg transition-colors flex items-center justify-center gap-2 ${
              preview?.can_complete
                ? 'bg-green-600 hover:bg-green-700 text-white'
                : 'bg-gray-300 text-gray-500 cursor-not-allowed'
            }`}
          >
            {isCompleting ? (
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
            ) : (
              <>
                <CheckCircle className="w-4 h-4" />
                Complete
              </>
            )}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

// Workflow Card Component
const WorkflowCard: React.FC<{
  execution: WorkflowExecution;
  onSelect: () => void;
  onViewDetails: () => void;
  onDelete: () => void;
  onComplete: () => void;
  onReview: () => void;
  isSelected: boolean;
}> = ({ execution, onSelect, onViewDetails, onDelete, onComplete, onReview, isSelected }) => {
  const statusColors: Record<string, string> = {
    active: 'bg-green-500',
    paused: 'bg-yellow-500',
    completed: 'bg-blue-500',
    failed: 'bg-red-500',
    pending_final_review: 'bg-amber-500',
  };

  // Show "Mark Complete" button for active workflows with no active work
  const canShowComplete = execution.status === 'active' &&
    (execution.stats?.active_tasks || 0) === 0 &&
    (execution.stats?.active_agents || 0) === 0;

  const isPendingReview = execution.status === 'pending_final_review';

  const handleClick = () => {
    if (isPendingReview) {
      onReview();
    } else {
      onSelect();
      onViewDetails();
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ scale: 1.02 }}
      className={`bg-white rounded-lg shadow-md p-4 border-2 transition-all cursor-pointer ${
        isSelected ? 'border-blue-500 ring-2 ring-blue-200' : isPendingReview ? 'border-amber-400 ring-2 ring-amber-200' : 'border-transparent hover:border-gray-200'
      }`}
      onClick={handleClick}
    >
      {/* Pending Review Banner */}
      {isPendingReview && (
        <div className="flex items-center gap-2 mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg animate-pulse">
          <GitMerge className="w-4 h-4 text-amber-600" />
          <span className="text-sm font-medium text-amber-800">Awaiting Final Review</span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onReview();
            }}
            className="ml-auto flex items-center gap-1 px-2 py-1 bg-amber-500 hover:bg-amber-600 text-white rounded text-xs font-medium transition-colors"
          >
            <Eye className="w-3 h-3" />
            Review Now
          </button>
        </div>
      )}

      {/* Header with status badge */}
      <div className="flex justify-between items-start mb-3">
        <span className={`px-2 py-1 rounded text-xs font-medium ${statusColors[execution.status] || 'bg-gray-500'} text-white`}>
          {execution.status === 'pending_final_review' ? 'PENDING REVIEW' : execution.status.toUpperCase()}
        </span>
        <span className="text-gray-500 text-sm">{execution.definition_name}</span>
      </div>

      {/* Title/Description */}
      <h3 className="text-lg font-semibold text-gray-800 mb-2">
        {execution.description || execution.definition_name}
      </h3>

      {/* Activity by Phase - show active work distribution */}
      <div className="mb-3">
        <div className="text-sm text-gray-500 mb-1">Current Activity</div>
        <div className="flex gap-2 text-xs">
          <span className="bg-gray-100 px-2 py-1 rounded text-gray-700">
            {execution.stats?.active_tasks || 0} active tasks
          </span>
          <span className="bg-gray-100 px-2 py-1 rounded text-gray-700">
            {execution.stats?.active_agents || 0} agents
          </span>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-4 gap-2 mb-3 text-center">
        <div className="bg-gray-50 rounded p-2">
          <div className="text-lg font-bold text-gray-800">{execution.stats?.total_tasks || 0}</div>
          <div className="text-xs text-gray-500">Tasks</div>
        </div>
        <div className="bg-gray-50 rounded p-2">
          <div className="text-lg font-bold text-gray-800">{execution.stats?.active_agents || 0}</div>
          <div className="text-xs text-gray-500">Agents</div>
        </div>
        <div className="bg-gray-50 rounded p-2">
          <div className="text-lg font-bold text-gray-800">{execution.stats?.done_tasks || 0}</div>
          <div className="text-xs text-gray-500">Done</div>
        </div>
        <div className="bg-gray-50 rounded p-2">
          <div className="text-lg font-bold text-green-600">
            {formatDuration(execution.created_at)}
          </div>
          <div className="text-xs text-gray-500">Running</div>
        </div>
      </div>

      {/* Started time and actions */}
      <div className="flex justify-between items-center text-xs text-gray-500">
        <span>Started: {new Date(execution.created_at).toLocaleString()}</span>
        <div className="flex items-center gap-3">
          {canShowComplete && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onComplete();
              }}
              className="text-green-600 hover:text-green-800 transition-colors p-1 rounded hover:bg-green-50 flex items-center gap-1"
              title="Mark workflow as complete"
            >
              <CheckCircle className="w-4 h-4" />
              <span className="text-xs">Complete</span>
            </button>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="text-gray-400 hover:text-red-600 transition-colors p-1 rounded hover:bg-red-50"
            title="Delete workflow"
          >
            <Trash2 className="w-4 h-4" />
          </button>
          <span className="text-blue-600 flex items-center gap-1">
            View Details <ExternalLink className="w-3 h-3" />
          </span>
        </div>
      </div>
    </motion.div>
  );
};

// Main Page Component
export default function WorkflowExecutions() {
  const { executions, definitions, loading, selectedExecutionId, selectExecution, refetch } = useWorkflow();
  const [showModal, setShowModal] = useState(false);
  const [filter, setFilter] = useState<'all' | 'active'>('all');
  const [detailExecution, setDetailExecution] = useState<WorkflowExecution | null>(null);
  const [deleteWorkflowId, setDeleteWorkflowId] = useState<string | null>(null);
  const [deleteWorkflowName, setDeleteWorkflowName] = useState<string | undefined>(undefined);
  const [completeWorkflowId, setCompleteWorkflowId] = useState<string | null>(null);
  const [completeWorkflowName, setCompleteWorkflowName] = useState<string | undefined>(undefined);
  const [reviewWorkflowId, setReviewWorkflowId] = useState<string | null>(null);
  const [reviewWorkflowName, setReviewWorkflowName] = useState<string | undefined>(undefined);

  // Pending review workflows should appear in their own section
  const pendingReviewExecutions = executions.filter(e => e.status === 'pending_final_review');
  const activeExecutions = executions.filter(e => e.status === 'active');
  const inactiveExecutions = executions.filter(e => e.status !== 'active' && e.status !== 'pending_final_review');

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-800 flex items-center">
            <Workflow className="w-8 h-8 mr-3 text-blue-600" />
            Workflows
          </h1>
          <p className="text-gray-600 mt-1">Manage workflow definitions and executions</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg flex items-center gap-2 transition-colors"
        >
          <Rocket className="w-4 h-4" />
          Launch Workflow
        </button>
      </div>

      {/* Workflow Definitions Section */}
      <div className="bg-white rounded-lg shadow-md p-4">
        <h2 className="text-lg font-semibold text-gray-800 mb-3 flex items-center gap-2">
          <Layers className="w-5 h-5 text-purple-600" />
          Loaded Workflow Definitions ({definitions.length})
        </h2>
        {definitions.length === 0 ? (
          <p className="text-gray-500 text-sm">No workflow definitions loaded</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {definitions.map((def) => (
              <div key={def.id} className="bg-purple-50 border border-purple-200 rounded-lg p-3">
                <div className="font-medium text-gray-800">{def.name}</div>
                <div className="text-sm text-gray-600">{def.description}</div>
                <div className="text-xs text-purple-600 mt-1">
                  {def.phases_count} phases • ID: {def.id}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        <button
          onClick={() => setFilter('all')}
          className={`px-4 py-2 rounded-lg transition-colors ${
            filter === 'all'
              ? 'bg-blue-600 text-white'
              : 'bg-white text-gray-700 hover:bg-gray-100'
          }`}
        >
          All ({executions.length})
        </button>
        <button
          onClick={() => setFilter('active')}
          className={`px-4 py-2 rounded-lg transition-colors ${
            filter === 'active'
              ? 'bg-blue-600 text-white'
              : 'bg-white text-gray-700 hover:bg-gray-100'
          }`}
        >
          Active ({activeExecutions.length})
        </button>
      </div>

      {/* Pending Final Review Section */}
      {pendingReviewExecutions.length > 0 && (filter === 'all' || filter === 'active') && (
        <div>
          <h2 className="text-lg font-semibold text-amber-700 mb-4 flex items-center gap-2">
            <GitMerge className="w-5 h-5 text-amber-500" />
            Awaiting Final Review ({pendingReviewExecutions.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {pendingReviewExecutions.map((execution) => (
              <WorkflowCard
                key={execution.id}
                execution={execution}
                onSelect={() => selectExecution(execution.id)}
                onViewDetails={() => setDetailExecution(execution)}
                onDelete={() => {
                  setDeleteWorkflowId(execution.id);
                  setDeleteWorkflowName(execution.description || execution.definition_name);
                }}
                onComplete={() => {
                  setCompleteWorkflowId(execution.id);
                  setCompleteWorkflowName(execution.description || execution.definition_name);
                }}
                onReview={() => {
                  setReviewWorkflowId(execution.id);
                  setReviewWorkflowName(execution.description || execution.definition_name);
                }}
                isSelected={selectedExecutionId === execution.id}
              />
            ))}
          </div>
        </div>
      )}

      {/* Active Section */}
      {activeExecutions.length > 0 && (filter === 'all' || filter === 'active') && (
        <div>
          <h2 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <span className="w-2 h-2 bg-green-500 rounded-full"></span>
            Active ({activeExecutions.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {activeExecutions.map((execution) => (
              <WorkflowCard
                key={execution.id}
                execution={execution}
                onSelect={() => selectExecution(execution.id)}
                onViewDetails={() => setDetailExecution(execution)}
                onDelete={() => {
                  setDeleteWorkflowId(execution.id);
                  setDeleteWorkflowName(execution.description || execution.definition_name);
                }}
                onComplete={() => {
                  setCompleteWorkflowId(execution.id);
                  setCompleteWorkflowName(execution.description || execution.definition_name);
                }}
                onReview={() => {
                  setReviewWorkflowId(execution.id);
                  setReviewWorkflowName(execution.description || execution.definition_name);
                }}
                isSelected={selectedExecutionId === execution.id}
              />
            ))}
          </div>
        </div>
      )}

      {/* Inactive Section */}
      {inactiveExecutions.length > 0 && filter === 'all' && (
        <div>
          <h2 className="text-lg font-semibold text-gray-500 mb-4">
            Completed/Failed ({inactiveExecutions.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {inactiveExecutions.map((execution) => (
              <WorkflowCard
                key={execution.id}
                execution={execution}
                onSelect={() => selectExecution(execution.id)}
                onViewDetails={() => setDetailExecution(execution)}
                onDelete={() => {
                  setDeleteWorkflowId(execution.id);
                  setDeleteWorkflowName(execution.description || execution.definition_name);
                }}
                onComplete={() => {
                  setCompleteWorkflowId(execution.id);
                  setCompleteWorkflowName(execution.description || execution.definition_name);
                }}
                onReview={() => {
                  setReviewWorkflowId(execution.id);
                  setReviewWorkflowName(execution.description || execution.definition_name);
                }}
                isSelected={selectedExecutionId === execution.id}
              />
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {executions.length === 0 && (
        <div className="bg-white rounded-lg shadow-md p-12 text-center">
          <Workflow className="w-16 h-16 mx-auto mb-4 text-gray-300" />
          <div className="text-gray-500 mb-4">No workflow executions yet</div>
          <button
            onClick={() => setShowModal(true)}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition-colors"
          >
            Start Your First Workflow
          </button>
        </div>
      )}

      {/* Launch Workflow Modal */}
      <LaunchWorkflowModal
        open={showModal}
        onClose={() => setShowModal(false)}
        onLaunch={(workflowId) => {
          // Select the newly launched workflow
          selectExecution(workflowId);
        }}
      />

      {/* Detail Modal */}
      <AnimatePresence>
        {detailExecution && (
          <WorkflowDetailModal
            execution={detailExecution}
            onClose={() => setDetailExecution(null)}
          />
        )}
      </AnimatePresence>

      {/* Delete Workflow Dialog */}
      <DeleteWorkflowDialog
        open={deleteWorkflowId !== null}
        workflowId={deleteWorkflowId}
        workflowName={deleteWorkflowName}
        onClose={() => {
          setDeleteWorkflowId(null);
          setDeleteWorkflowName(undefined);
        }}
        onDeleted={() => {
          // Clear selection if deleted workflow was selected
          if (selectedExecutionId === deleteWorkflowId) {
            selectExecution(null);
          }
          // Refresh the executions list
          refetch();
        }}
      />

      {/* Complete Workflow Dialog */}
      <CompleteWorkflowDialog
        open={completeWorkflowId !== null}
        workflowId={completeWorkflowId}
        workflowName={completeWorkflowName}
        onClose={() => {
          setCompleteWorkflowId(null);
          setCompleteWorkflowName(undefined);
        }}
        onCompleted={() => {
          // Refresh the executions list
          refetch();
        }}
      />

      {/* Final Diff Review Modal */}
      <FinalDiffReviewModal
        open={reviewWorkflowId !== null}
        workflowId={reviewWorkflowId || ''}
        workflowName={reviewWorkflowName}
        onClose={() => {
          setReviewWorkflowId(null);
          setReviewWorkflowName(undefined);
        }}
        onApproved={() => {
          // Refresh the executions list after approval
          refetch();
        }}
        onRejected={() => {
          // Refresh the executions list after rejection
          refetch();
        }}
      />
    </div>
  );
}
