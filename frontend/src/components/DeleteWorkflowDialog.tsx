import React, { useState, useEffect } from 'react';
import {
  Trash2,
  AlertTriangle,
  Loader2,
  AlertCircle,
  CheckCircle,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { apiService } from '@/services/api';

interface DeletionPreview {
  workflow_id: string;
  workflow_name: string;
  workflow_description: string;
  workflow_status: string;
  is_active: boolean;
  active_agents: Array<{
    id: string;
    status: string;
    current_task_id: string | null;
  }>;
  counts: {
    phases: number;
    tasks: number;
    tickets: number;
    phase_executions: number;
    memories: number;
    agent_results: number;
    validation_reviews: number;
    ticket_comments: number;
    ticket_history: number;
    ticket_commits: number;
    workflow_results: number;
    diagnostic_runs: number;
    board_config: number;
  };
}

interface DeleteWorkflowDialogProps {
  open: boolean;
  workflowId: string | null;
  workflowName?: string;
  onClose: () => void;
  onDeleted: () => void;
}

const DeleteWorkflowDialog: React.FC<DeleteWorkflowDialogProps> = ({
  open,
  workflowId,
  workflowName,
  onClose,
  onDeleted,
}) => {
  const [preview, setPreview] = useState<DeletionPreview | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forceTerminate, setForceTerminate] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [deleteSuccess, setDeleteSuccess] = useState(false);

  useEffect(() => {
    if (open && workflowId) {
      fetchPreview();
    } else {
      resetState();
    }
  }, [open, workflowId]);

  const resetState = () => {
    setPreview(null);
    setIsLoading(false);
    setIsDeleting(false);
    setError(null);
    setForceTerminate(false);
    setConfirmText('');
    setDeleteSuccess(false);
  };

  const fetchPreview = async () => {
    if (!workflowId) return;

    setIsLoading(true);
    setError(null);

    try {
      const data = await apiService.getWorkflowDeletionPreview(workflowId);
      setPreview(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to load deletion preview');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!workflowId || !preview) return;

    // Require force flag for active workflows
    if (preview.is_active && !forceTerminate) {
      setError('Workflow is active. Check "Force terminate agents" to proceed.');
      return;
    }

    setIsDeleting(true);
    setError(null);

    try {
      await apiService.deleteWorkflowExecution(workflowId, forceTerminate);
      setDeleteSuccess(true);
      setTimeout(() => {
        onDeleted();
        onClose();
      }, 1500);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to delete workflow');
    } finally {
      setIsDeleting(false);
    }
  };

  const getTotalCount = () => {
    if (!preview) return 0;
    return Object.values(preview.counts).reduce((sum, count) => sum + count, 0) + 1; // +1 for workflow itself
  };

  const canDelete = confirmText === 'DELETE' && (!preview?.is_active || forceTerminate);

  const renderContent = () => {
    if (deleteSuccess) {
      return (
        <div className="flex flex-col items-center justify-center py-8">
          <CheckCircle className="w-16 h-16 text-green-500 mb-4" />
          <h3 className="text-lg font-medium text-green-600">Workflow Deleted</h3>
          <p className="text-sm text-gray-500 mt-2">
            The workflow and all associated data have been permanently removed.
          </p>
        </div>
      );
    }

    if (isLoading) {
      return (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
        </div>
      );
    }

    if (error && !preview) {
      return (
        <div className="flex flex-col items-center justify-center py-8">
          <AlertCircle className="w-12 h-12 text-red-500 mb-4" />
          <p className="text-red-500">{error}</p>
          <Button variant="outline" onClick={fetchPreview} className="mt-4">
            Retry
          </Button>
        </div>
      );
    }

    if (!preview) return null;

    return (
      <div className="space-y-4">
        <DialogDescription className="text-red-600 font-medium">
          This action cannot be undone. All data will be permanently deleted.
        </DialogDescription>

        {/* Workflow Info */}
        <div className="p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
          <h4 className="font-medium text-gray-900 dark:text-white mb-2">
            Workflow Details
          </h4>
          <dl className="space-y-1 text-sm">
            <div className="flex justify-between">
              <dt className="text-gray-500">Name:</dt>
              <dd className="font-medium">{preview.workflow_name || workflowName || 'Unnamed'}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Status:</dt>
              <dd>
                <Badge
                  variant={preview.is_active ? 'default' : 'secondary'}
                  className={preview.is_active ? 'bg-green-500' : ''}
                >
                  {preview.workflow_status}
                </Badge>
              </dd>
            </div>
            {preview.workflow_description && (
              <div>
                <dt className="text-gray-500">Description:</dt>
                <dd className="text-gray-700 dark:text-gray-300 mt-1 text-xs">
                  {preview.workflow_description}
                </dd>
              </div>
            )}
          </dl>
        </div>

        {/* Active Agents Warning */}
        {preview.is_active && preview.active_agents.length > 0 && (
          <div className="p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
              <div>
                <h4 className="font-medium text-amber-800 dark:text-amber-200">
                  Active Agents Detected
                </h4>
                <p className="text-sm text-amber-700 dark:text-amber-300 mt-1">
                  {preview.active_agents.length} agent(s) are currently working on this workflow.
                  They will be forcefully terminated.
                </p>
                <ul className="text-xs text-amber-600 dark:text-amber-400 mt-2 space-y-1">
                  {preview.active_agents.slice(0, 3).map((agent) => (
                    <li key={agent.id}>• Agent {agent.id.slice(0, 8)}... ({agent.status})</li>
                  ))}
                  {preview.active_agents.length > 3 && (
                    <li>• ... and {preview.active_agents.length - 3} more</li>
                  )}
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* Data to be Deleted */}
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <h4 className="font-medium text-red-800 dark:text-red-200 mb-3">
            Data to be Permanently Deleted ({getTotalCount()} items)
          </h4>
          <ScrollArea className="h-[150px]">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="flex justify-between">
                <span className="text-red-700 dark:text-red-300">Phases:</span>
                <span className="font-medium">{preview.counts.phases}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-red-700 dark:text-red-300">Tasks:</span>
                <span className="font-medium">{preview.counts.tasks}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-red-700 dark:text-red-300">Tickets:</span>
                <span className="font-medium">{preview.counts.tickets}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-red-700 dark:text-red-300">Memories:</span>
                <span className="font-medium">{preview.counts.memories}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-red-700 dark:text-red-300">Agent Results:</span>
                <span className="font-medium">{preview.counts.agent_results}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-red-700 dark:text-red-300">Validations:</span>
                <span className="font-medium">{preview.counts.validation_reviews}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-red-700 dark:text-red-300">Comments:</span>
                <span className="font-medium">{preview.counts.ticket_comments}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-red-700 dark:text-red-300">Workflow Results:</span>
                <span className="font-medium">{preview.counts.workflow_results}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-red-700 dark:text-red-300">Diagnostics:</span>
                <span className="font-medium">{preview.counts.diagnostic_runs}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-red-700 dark:text-red-300">Phase Executions:</span>
                <span className="font-medium">{preview.counts.phase_executions}</span>
              </div>
            </div>
          </ScrollArea>
        </div>

        {/* Force Terminate Checkbox (only for active workflows) */}
        {preview.is_active && (
          <label className="flex items-center gap-2 cursor-pointer p-3 border border-amber-300 rounded-lg bg-amber-50 dark:bg-amber-900/10">
            <input
              type="checkbox"
              checked={forceTerminate}
              onChange={(e) => setForceTerminate(e.target.checked)}
              className="w-4 h-4 rounded border-amber-400 text-amber-600 focus:ring-amber-500"
            />
            <span className="text-sm text-amber-800 dark:text-amber-200 font-medium">
              Force terminate {preview.active_agents.length} active agent(s) before deletion
            </span>
          </label>
        )}

        {/* Confirmation Input */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Type <span className="font-bold text-red-600">DELETE</span> to confirm:
          </label>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="w-full px-3 py-2 border rounded-md bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-red-500"
            placeholder="DELETE"
          />
        </div>

        {error && (
          <div className="flex items-center gap-2 text-red-500 text-sm">
            <AlertCircle className="w-4 h-4" />
            {error}
          </div>
        )}
      </div>
    );
  };

  return (
    <Dialog open={open} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-red-600">
            <Trash2 className="w-5 h-5" />
            Delete Workflow
          </DialogTitle>
        </DialogHeader>

        {renderContent()}

        {!deleteSuccess && preview && (
          <DialogFooter>
            <Button variant="outline" onClick={onClose} disabled={isDeleting}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={!canDelete || isDeleting}
              className="bg-red-600 hover:bg-red-700"
            >
              {isDeleting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Deleting...
                </>
              ) : (
                <>
                  <Trash2 className="w-4 h-4 mr-2" />
                  Delete Permanently
                </>
              )}
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
};

export default DeleteWorkflowDialog;
