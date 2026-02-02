/**
 * WebSocket Hook for Real-time Updates.
 *
 * Manages WebSocket connection with JWT authentication and auto-reconnection.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { getAccessToken } from '../api/auth';

interface WebSocketMessage {
  type: string;
  timestamp?: string;
  data: any;
}

interface BotStatus {
  id: number;
  name: string;
  status: string;
  symbol: string;
}

interface UserStatus {
  user_id: number;
  bots: BotStatus[];
  bot_count: number;
  active_bots: number;
}

interface TradeNotification {
  trade_id: number;
  symbol: string;
  side: string;
  entry_price: number;
  pnl?: number;
}

interface RiskAlert {
  alert_type: string;
  message: string;
  severity: string;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  userStatus: UserStatus | null;
  lastTrade: TradeNotification | null;
  lastAlert: RiskAlert | null;
  error: string | null;
  reconnect: () => void;
}

export function useWebSocket(): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false);
  const [userStatus, setUserStatus] = useState<UserStatus | null>(null);
  const [lastTrade, setLastTrade] = useState<TradeNotification | null>(null);
  const [lastAlert, setLastAlert] = useState<RiskAlert | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const MAX_RECONNECT_ATTEMPTS = 5;
  const RECONNECT_DELAY_MS = 2000;

  const connect = useCallback(() => {
    const token = getAccessToken();
    if (!token) {
      setError('Not authenticated');
      return;
    }

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    // Create WebSocket URL with token
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/user?token=${token}`;

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
        reconnectAttemptsRef.current = 0;
        console.log('WebSocket connected');
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);

          switch (message.type) {
            case 'status':
              setUserStatus(message.data);
              break;

            case 'trade':
              setLastTrade(message.data);
              break;

            case 'bot_status':
              // Update bot status in userStatus
              setUserStatus((prev) => {
                if (!prev) return prev;
                return {
                  ...prev,
                  bots: prev.bots.map((bot) =>
                    bot.id === message.data.bot_id
                      ? { ...bot, status: message.data.status }
                      : bot
                  ),
                };
              });
              break;

            case 'risk_alert':
              setLastAlert(message.data);
              break;

            case 'pong':
              // Heartbeat response, ignore
              break;

            default:
              console.log('Unknown WebSocket message type:', message.type);
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        wsRef.current = null;

        if (event.code === 4001) {
          // Authentication error, don't reconnect
          setError('Authentication failed');
          return;
        }

        // Attempt to reconnect
        if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current++;
          const delay = RECONNECT_DELAY_MS * Math.pow(2, reconnectAttemptsRef.current - 1);
          console.log(`WebSocket disconnected, reconnecting in ${delay}ms...`);

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else {
          setError('Connection lost. Please refresh the page.');
        }
      };

      ws.onerror = (event) => {
        console.error('WebSocket error:', event);
        setError('Connection error');
      };

      wsRef.current = ws;
    } catch (e) {
      console.error('Failed to create WebSocket:', e);
      setError('Failed to connect');
    }
  }, []);

  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    setError(null);
    connect();
  }, [connect]);

  // Connect on mount
  useEffect(() => {
    connect();

    // Cleanup on unmount
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  // Send ping periodically to keep connection alive
  useEffect(() => {
    if (!isConnected || !wsRef.current) return;

    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000); // Ping every 30 seconds

    return () => clearInterval(pingInterval);
  }, [isConnected]);

  return {
    isConnected,
    userStatus,
    lastTrade,
    lastAlert,
    error,
    reconnect,
  };
}
