import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
  ChevronRight,
  FilePlus,
  FileX,
  FileEdit,
  FileCode,
  Loader2,
  GitBranch,
  GitCommit,
  Check,
  XCircle,
  AlertTriangle,
  CheckCircle,
  AlertCircle,
} from 'lucide-react';
import { format } from 'date-fns';
import { apiService } from '@/services/api';
import { cn } from '@/lib/utils';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';

interface FinalDiffReviewModalProps {
  workflowId: string;
  workflowName?: string;
  open: boolean;
  onClose: () => void;
  onApproved: () => void;
  onRejected: () => void;
}

const FinalDiffReviewModal: React.FC<FinalDiffReviewModalProps> = ({
  workflowId,
  workflowName,
  open,
  onClose,
  onApproved,
  onRejected,
}) => {
  const queryClient = useQueryClient();
  const [expandedFiles, setExpandedFiles] = useState<Set<string>>(new Set());
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [deleteBranchOnReject, setDeleteBranchOnReject] = useState(false);
  const [actionSuccess, setActionSuccess] = useState<'approved' | 'rejected' | null>(null);

  const { data: diffData, isLoading, error } = useQuery({
    queryKey: ['workflow-final-diff', workflowId],
    queryFn: () => apiService.getWorkflowFinalDiff(workflowId),
    enabled: open && !!workflowId,
  });

  const approveMutation = useMutation({
    mutationFn: () => apiService.approveWorkflowMerge(workflowId, 'ui-user'),
    onSuccess: () => {
      setActionSuccess('approved');
      queryClient.invalidateQueries({ queryKey: ['workflow-executions'] });
      queryClient.invalidateQueries({ queryKey: ['workflow-execution-detail', workflowId] });
      setTimeout(() => {
        onApproved();
        onClose();
      }, 1500);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: () =>
      apiService.rejectWorkflowMerge(workflowId, 'ui-user', rejectReason || undefined, deleteBranchOnReject),
    onSuccess: () => {
      setActionSuccess('rejected');
      queryClient.invalidateQueries({ queryKey: ['workflow-executions'] });
      queryClient.invalidateQueries({ queryKey: ['workflow-execution-detail', workflowId] });
      setTimeout(() => {
        onRejected();
        onClose();
      }, 1500);
    },
  });

  const toggleFile = (filePath: string) => {
    setExpandedFiles((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(filePath)) {
        newSet.delete(filePath);
      } else {
        newSet.add(filePath);
      }
      return newSet;
    });
  };

  const getFileIcon = (status: string) => {
    switch (status) {
      case 'added':
        return <FilePlus className="w-4 h-4 text-green-600" />;
      case 'deleted':
        return <FileX className="w-4 h-4 text-red-600" />;
      case 'modified':
        return <FileEdit className="w-4 h-4 text-blue-600" />;
      case 'renamed':
        return <FileCode className="w-4 h-4 text-purple-600" />;
      default:
        return <FileCode className="w-4 h-4 text-gray-600" />;
    }
  };

  const renderDiffLine = (line: string, index: number) => {
    let bgColor = '';
    let textColor = 'text-gray-900';
    let linePrefix = ' ';

    if (line.startsWith('+')) {
      bgColor = 'bg-green-50';
      textColor = 'text-green-900';
      linePrefix = '+';
    } else if (line.startsWith('-')) {
      bgColor = 'bg-red-50';
      textColor = 'text-red-900';
      linePrefix = '-';
    } else if (line.startsWith('@@')) {
      bgColor = 'bg-blue-50';
      textColor = 'text-blue-900';
      linePrefix = '@';
    }

    return (
      <div key={index} className={cn('flex font-mono text-xs', bgColor)}>
        <span className={cn('w-8 flex-shrink-0 text-center select-none', textColor)}>
          {linePrefix}
        </span>
        <pre className={cn('flex-1 px-2 overflow-x-auto', textColor)}>
          <code>{line}</code>
        </pre>
      </div>
    );
  };

  const handleReject = () => {
    if (showRejectForm) {
      rejectMutation.mutate();
    } else {
      setShowRejectForm(true);
    }
  };

  const renderSuccessState = () => (
    <div className="flex flex-col items-center justify-center py-12">
      {actionSuccess === 'approved' ? (
        <>
          <CheckCircle className="w-16 h-16 text-green-500 mb-4" />
          <h3 className="text-lg font-medium text-green-600">Merge Approved!</h3>
          <p className="text-sm text-gray-500 mt-2">
            The workflow branch has been successfully merged to main.
          </p>
        </>
      ) : (
        <>
          <XCircle className="w-16 h-16 text-red-500 mb-4" />
          <h3 className="text-lg font-medium text-red-600">Merge Rejected</h3>
          <p className="text-sm text-gray-500 mt-2">
            The workflow has been marked as failed.
          </p>
        </>
      )}
    </div>
  );

  const renderContent = () => {
    if (actionSuccess) {
      return renderSuccessState();
    }

    if (isLoading) {
      return (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
          <span className="ml-3 text-gray-500">Loading diff data...</span>
        </div>
      );
    }

    if (error) {
      return (
        <div className="flex flex-col items-center justify-center py-12">
          <AlertCircle className="w-12 h-12 text-red-500 mb-4" />
          <p className="text-red-500 mb-4">Failed to load diff data</p>
          <p className="text-sm text-gray-500">{(error as Error).message}</p>
        </div>
      );
    }

    if (!diffData) {
      return (
        <div className="flex items-center justify-center py-12 text-gray-500">
          <p>No diff data available</p>
        </div>
      );
    }

    return (
      <div className="space-y-4">
        {/* Branch Info */}
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-2 bg-gray-100 px-3 py-1.5 rounded-lg">
            <GitBranch className="w-4 h-4 text-purple-600" />
            <span className="font-mono">{diffData.workflow_branch}</span>
          </div>
          <span className="text-gray-400">→</span>
          <div className="flex items-center gap-2 bg-gray-100 px-3 py-1.5 rounded-lg">
            <GitBranch className="w-4 h-4 text-blue-600" />
            <span className="font-mono">{diffData.base_branch}</span>
          </div>
        </div>

        {/* Stats Summary */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-gray-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-gray-800">{diffData.stats.total_files}</div>
            <div className="text-xs text-gray-500">Files Changed</div>
          </div>
          <div className="bg-green-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-green-600">+{diffData.stats.total_insertions}</div>
            <div className="text-xs text-gray-500">Insertions</div>
          </div>
          <div className="bg-red-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-red-600">-{diffData.stats.total_deletions}</div>
            <div className="text-xs text-gray-500">Deletions</div>
          </div>
        </div>

        {/* Merge Conflicts Warning */}
        {!diffData.can_merge && diffData.merge_conflicts && diffData.merge_conflicts.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
              <div>
                <h4 className="font-medium text-amber-800">Merge Conflicts Detected</h4>
                <p className="text-sm text-amber-700 mt-1">
                  The following files have conflicts that need to be resolved:
                </p>
                <ul className="text-xs text-amber-600 mt-2 space-y-1 font-mono">
                  {diffData.merge_conflicts.map((file, i) => (
                    <li key={i}>• {file}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* Commits List */}
        {diffData.commits.length > 0 && (
          <div className="border rounded-lg">
            <div className="px-4 py-3 bg-gray-50 border-b flex items-center gap-2">
              <GitCommit className="w-4 h-4 text-gray-600" />
              <span className="font-medium text-gray-700">Commits ({diffData.commits.length})</span>
            </div>
            <ScrollArea className="max-h-32">
              <div className="divide-y">
                {diffData.commits.map((commit) => (
                  <div key={commit.sha} className="px-4 py-2 flex items-start gap-3">
                    <div className="font-mono text-xs text-gray-500 flex-shrink-0">
                      {commit.sha.slice(0, 7)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-gray-800 truncate">{commit.message}</div>
                      <div className="text-xs text-gray-500">
                        {commit.author} • {format(new Date(commit.timestamp), 'MMM d, HH:mm')}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        )}

        {/* Files Changed */}
        <div className="space-y-2">
          <h4 className="font-medium text-gray-700">Files Changed</h4>
          <ScrollArea className="max-h-[300px]">
            <div className="space-y-2">
              {diffData.files.map((file, fileIndex) => {
                const isExpanded = expandedFiles.has(file.path);
                return (
                  <div key={fileIndex} className="border rounded-lg overflow-hidden">
                    <button
                      onClick={() => toggleFile(file.path)}
                      className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
                    >
                      <div className="flex items-center space-x-3">
                        {isExpanded ? (
                          <ChevronDown className="w-4 h-4 text-gray-600" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-gray-600" />
                        )}
                        {getFileIcon(file.status)}
                        <span className="font-mono text-sm text-gray-900">{file.path}</span>
                        {file.old_path && (
                          <span className="text-xs text-gray-500">← {file.old_path}</span>
                        )}
                      </div>
                      <div className="flex items-center space-x-4 text-xs">
                        <span
                          className={cn(
                            'px-2 py-1 rounded',
                            file.status === 'added' && 'bg-green-100 text-green-700',
                            file.status === 'deleted' && 'bg-red-100 text-red-700',
                            file.status === 'modified' && 'bg-blue-100 text-blue-700',
                            file.status === 'renamed' && 'bg-purple-100 text-purple-700'
                          )}
                        >
                          {file.status}
                        </span>
                        <span className="text-green-600">+{file.insertions}</span>
                        <span className="text-red-600">-{file.deletions}</span>
                      </div>
                    </button>

                    {isExpanded && file.diff && (
                      <div className="border-t bg-white">
                        <div className="overflow-x-auto">
                          {file.diff.split('\n').map((line, lineIndex) =>
                            renderDiffLine(line, lineIndex)
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </div>

        {/* Reject Reason Form */}
        {showRejectForm && (
          <div className="border border-red-200 rounded-lg p-4 bg-red-50 space-y-3">
            <h4 className="font-medium text-red-800">Rejection Details</h4>
            <div>
              <label className="block text-sm text-red-700 mb-1">
                Reason (optional)
              </label>
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                className="w-full px-3 py-2 border rounded-md bg-white text-gray-800 focus:outline-none focus:ring-2 focus:ring-red-500"
                rows={2}
                placeholder="Why are you rejecting this merge?"
              />
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={deleteBranchOnReject}
                onChange={(e) => setDeleteBranchOnReject(e.target.checked)}
                className="w-4 h-4 rounded border-red-400 text-red-600 focus:ring-red-500"
              />
              <span className="text-sm text-red-700">Delete workflow branch</span>
            </label>
          </div>
        )}

        {/* Error Display */}
        {(approveMutation.error || rejectMutation.error) && (
          <div className="flex items-center gap-2 text-red-500 text-sm bg-red-50 p-3 rounded-lg">
            <AlertCircle className="w-4 h-4" />
            {(approveMutation.error as Error)?.message ||
              (rejectMutation.error as Error)?.message ||
              'An error occurred'}
          </div>
        )}
      </div>
    );
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitBranch className="w-5 h-5 text-purple-600" />
            Final Diff Review
          </DialogTitle>
          <DialogDescription>
            {workflowName || `Workflow ${workflowId.slice(0, 8)}`}
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="flex-1 px-1">
          {renderContent()}
        </ScrollArea>

        {!actionSuccess && diffData && (
          <DialogFooter className="gap-2 sm:gap-2">
            {showRejectForm && (
              <Button
                variant="outline"
                onClick={() => setShowRejectForm(false)}
                disabled={rejectMutation.isPending}
              >
                Cancel
              </Button>
            )}
            <Button
              variant="destructive"
              onClick={handleReject}
              disabled={approveMutation.isPending || rejectMutation.isPending}
              className="bg-red-600 hover:bg-red-700"
            >
              {rejectMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Rejecting...
                </>
              ) : (
                <>
                  <XCircle className="w-4 h-4 mr-2" />
                  {showRejectForm ? 'Confirm Reject' : 'Reject'}
                </>
              )}
            </Button>
            {!showRejectForm && (
              <Button
                onClick={() => approveMutation.mutate()}
                disabled={!diffData.can_merge || approveMutation.isPending || rejectMutation.isPending}
                className="bg-green-600 hover:bg-green-700"
              >
                {approveMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Approving...
                  </>
                ) : (
                  <>
                    <Check className="w-4 h-4 mr-2" />
                    Approve & Merge
                  </>
                )}
              </Button>
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
};

export default FinalDiffReviewModal;
