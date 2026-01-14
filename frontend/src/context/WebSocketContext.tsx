import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';
import { WebSocketMessage } from '@/types';
import toast from 'react-hot-toast';

interface WebSocketContextType {
  isConnected: boolean;
  lastMessage: WebSocketMessage | null;
  lastUpdate: Date;
  subscribe: (event: string, callback: (data: any) => void) => () => void;
}

const WebSocketContext = createContext<WebSocketContextType | null>(null);

export const useWebSocket = () => {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useWebSocket must be used within WebSocketProvider');
  }
  return context;
};

interface WebSocketProviderProps {
  children: React.ReactNode;
}

export const WebSocketProvider: React.FC<WebSocketProviderProps> = ({ children }) => {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [lastUpdate, setLastUpdate] = useState(new Date());
  const subscribersRef = useRef<Map<string, Set<(data: any) => void>>>(new Map());
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Use a counter to track which WebSocket instance is current (handles StrictMode double-mount)
  const connectionIdRef = useRef(0);

  const subscribe = useCallback((event: string, callback: (data: any) => void) => {
    if (!subscribersRef.current.has(event)) {
      subscribersRef.current.set(event, new Set());
    }
    subscribersRef.current.get(event)!.add(callback);

    // Return unsubscribe function
    return () => {
      subscribersRef.current.get(event)?.delete(callback);
    };
  }, []);

  useEffect(() => {
    // Increment connection ID to invalidate any previous WebSocket callbacks
    connectionIdRef.current += 1;
    const currentConnectionId = connectionIdRef.current;

    const connectWebSocket = () => {
      // Don't connect if this effect has been cleaned up
      if (connectionIdRef.current !== currentConnectionId) return;

      // Close existing connection if any
      if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
        wsRef.current.close();
      }

      const websocket = new WebSocket('ws://localhost:8000/ws');
      wsRef.current = websocket;

      websocket.onopen = () => {
        // Ignore if this is a stale WebSocket (from previous mount)
        if (connectionIdRef.current !== currentConnectionId) {
          websocket.close();
          return;
        }
        setIsConnected(true);
        toast.success('Connected to server', { duration: 2000 });
      };

      websocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WebSocketMessage;
          setLastMessage(data);
          setLastUpdate(new Date());

          // Notify subscribers
          const callbacks = subscribersRef.current.get(data.type);
          if (callbacks) {
            callbacks.forEach(callback => callback(data));
          }

          // Show notifications for important events
          switch (data.type) {
            case 'task_created':
              toast('New task created', { icon: '📋' });
              break;
            case 'task_completed':
              toast.success('Task completed!', { icon: '✅' });
              break;
            case 'agent_created':
              toast('New agent spawned', { icon: '🤖' });
              break;
            case 'guardian_analysis':
              // Silent update - no toast for frequent guardian analyses
              break;
            case 'conductor_analysis':
              // Silent update - no toast for frequent conductor analyses
              break;
            case 'steering_intervention':
              toast('Agent steered back on track', { icon: '🎯' });
              break;
            case 'duplicate_detected':
              toast.error('Duplicate work detected', { icon: '⚠️' });
              break;
            case 'results_reported':
              toast('New result submitted', { icon: '📝' });
              break;
            case 'result_validation_completed':
              toast.success('Result validation updated', { icon: '🔍' });
              break;
            case 'ticket_created':
              toast('New ticket created', { icon: '🎫' });
              break;
            case 'ticket_updated':
              // Silent update - too frequent
              break;
            case 'status_changed':
              toast('Ticket status changed', { icon: '🔄' });
              break;
            case 'comment_added':
              toast('New comment added', { icon: '💬' });
              break;
            case 'commit_linked':
              toast('Commit linked to ticket', { icon: '🔗' });
              break;
            case 'ticket_resolved':
              toast.success('Ticket resolved!', { icon: '✅' });
              break;
            case 'ticket_approved':
              toast.success('Ticket approved!', { icon: '✅' });
              break;
            case 'ticket_rejected':
              toast.error('Ticket rejected', { icon: '❌' });
              break;
            case 'ticket_deleted':
              toast('Ticket deleted', { icon: '🗑️' });
              break;
          }
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      websocket.onerror = () => {
        // Ignore errors from stale WebSocket instances (StrictMode double-mount)
        if (connectionIdRef.current !== currentConnectionId) return;
        // Suppress console logging - connection errors are handled by onclose/reconnect
      };

      websocket.onclose = (event) => {
        // Ignore close events from stale WebSocket instances
        if (connectionIdRef.current !== currentConnectionId) return;

        setIsConnected(false);

        // Only schedule reconnect if it wasn't a clean close (code 1000)
        if (event.code !== 1000) {
          // Schedule reconnect after 3 seconds
          reconnectTimeoutRef.current = setTimeout(() => {
            if (connectionIdRef.current === currentConnectionId) {
              connectWebSocket();
            }
          }, 3000);
        }
      };
    };

    connectWebSocket();

    return () => {
      // Clear any pending reconnect
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      
      // Close WebSocket connection cleanly
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted');
        wsRef.current = null;
      }
    };
  }, []);

  return (
    <WebSocketContext.Provider value={{ isConnected, lastMessage, lastUpdate, subscribe }}>
      {children}
    </WebSocketContext.Provider>
  );
};
