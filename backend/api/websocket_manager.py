"""
WebSocket manager for real-time updates.

Handles:
- Operation progress updates
- Worker status changes
- System alerts and notifications
- Log streaming
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Set, Optional, Any
from enum import Enum

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger


class EventType(str, Enum):
    """WebSocket event types."""
    OPERATION_UPDATE = "operation_update"
    WORKER_STATUS = "worker_status"
    SYSTEM_ALERT = "system_alert"
    LOG_ENTRY = "log_entry"
    HEARTBEAT = "heartbeat"


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts events to connected clients.

    Supports:
    - Multiple concurrent connections
    - Topic-based subscriptions
    - Automatic heartbeat/ping
    - Connection state management
    """

    def __init__(self):
        """Initialize WebSocket manager."""
        # Active connections: {connection_id: websocket}
        self.active_connections: Dict[str, WebSocket] = {}

        # Subscriptions: {topic: set of connection_ids}
        self.subscriptions: Dict[str, Set[str]] = {}

        # Connection metadata
        self.connection_metadata: Dict[str, Dict[str, Any]] = {}

        # Heartbeat task
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start WebSocket manager background tasks."""
        if not self._running:
            self._running = True
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("WebSocket manager started")

    async def stop(self):
        """Stop WebSocket manager and close all connections."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Close all active connections
        for connection_id, websocket in list(self.active_connections.items()):
            try:
                await websocket.close()
            except Exception:
                pass

        self.active_connections.clear()
        self.subscriptions.clear()
        self.connection_metadata.clear()
        logger.info("WebSocket manager stopped")

    async def connect(
        self,
        websocket: WebSocket,
        connection_id: str,
        user_id: Optional[int] = None,
        topics: Optional[List[str]] = None,
    ) -> None:
        """
        Register new WebSocket connection.

        Args:
            websocket: WebSocket connection
            connection_id: Unique connection identifier
            user_id: User ID (for auth/filtering)
            topics: Initial topics to subscribe to
        """
        await websocket.accept()

        self.active_connections[connection_id] = websocket
        self.connection_metadata[connection_id] = {
            "user_id": user_id,
            "connected_at": datetime.now(timezone.utc),
            "topics": set(),
        }

        # Subscribe to topics
        if topics:
            for topic in topics:
                await self.subscribe(connection_id, topic)

        logger.info(f"WebSocket connected: {connection_id} (user_id={user_id})")

    async def register_connection(
        self,
        websocket: WebSocket,
        connection_id: str,
        user_id: Optional[int] = None,
        topics: Optional[List[str]] = None,
    ) -> None:
        """
        Register WebSocket connection that has already been accepted.
        Use this when you need to accept the connection early (e.g., for auth validation).

        Args:
            websocket: WebSocket connection (already accepted)
            connection_id: Unique connection identifier
            user_id: User ID (for auth/filtering)
            topics: Initial topics to subscribe to
        """
        self.active_connections[connection_id] = websocket
        self.connection_metadata[connection_id] = {
            "user_id": user_id,
            "connected_at": datetime.now(timezone.utc),
            "topics": set(),
        }

        # Subscribe to topics
        if topics:
            for topic in topics:
                await self.subscribe(connection_id, topic)

        logger.info(f"WebSocket registered: {connection_id} (user_id={user_id})")

        # Send welcome message
        await self.send_to_connection(
            connection_id,
            {
                "event_type": "connected",
                "connection_id": connection_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "Connected to real-time updates",
            },
        )

    async def disconnect(self, connection_id: str) -> None:
        """
        Unregister WebSocket connection.

        Args:
            connection_id: Connection identifier
        """
        # Remove from subscriptions
        for topic in list(self.subscriptions.keys()):
            if connection_id in self.subscriptions[topic]:
                self.subscriptions[topic].remove(connection_id)
                if not self.subscriptions[topic]:
                    del self.subscriptions[topic]

        # Remove connection
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]

        if connection_id in self.connection_metadata:
            del self.connection_metadata[connection_id]

        logger.info(f"WebSocket disconnected: {connection_id}")

    async def subscribe(self, connection_id: str, topic: str) -> None:
        """
        Subscribe connection to a topic.

        Args:
            connection_id: Connection identifier
            topic: Topic name
        """
        if topic not in self.subscriptions:
            self.subscriptions[topic] = set()

        self.subscriptions[topic].add(connection_id)

        if connection_id in self.connection_metadata:
            self.connection_metadata[connection_id]["topics"].add(topic)

        logger.debug(f"Connection {connection_id} subscribed to topic: {topic}")

    async def unsubscribe(self, connection_id: str, topic: str) -> None:
        """
        Unsubscribe connection from a topic.

        Args:
            connection_id: Connection identifier
            topic: Topic name
        """
        if topic in self.subscriptions:
            self.subscriptions[topic].discard(connection_id)
            if not self.subscriptions[topic]:
                del self.subscriptions[topic]

        if connection_id in self.connection_metadata:
            self.connection_metadata[connection_id]["topics"].discard(topic)

        logger.debug(f"Connection {connection_id} unsubscribed from topic: {topic}")

    async def send_to_connection(
        self,
        connection_id: str,
        data: Dict[str, Any],
    ) -> bool:
        """
        Send data to a specific connection.

        Args:
            connection_id: Connection identifier
            data: Data to send

        Returns:
            True if sent successfully, False otherwise
        """
        if connection_id not in self.active_connections:
            return False

        websocket = self.active_connections[connection_id]

        try:
            await websocket.send_json(data)
            return True
        except WebSocketDisconnect:
            await self.disconnect(connection_id)
            return False
        except Exception as exc:
            logger.error(f"Error sending to connection {connection_id}: {exc}")
            await self.disconnect(connection_id)
            return False

    async def broadcast(
        self,
        data: Dict[str, Any],
        topic: Optional[str] = None,
        exclude: Optional[List[str]] = None,
    ) -> int:
        """
        Broadcast data to all connections or topic subscribers.

        Args:
            data: Data to broadcast
            topic: Optional topic to broadcast to (if None, broadcast to all)
            exclude: Optional list of connection IDs to exclude

        Returns:
            Number of connections that received the message
        """
        exclude = exclude or []

        # Determine target connections
        if topic:
            target_connections = self.subscriptions.get(topic, set())
        else:
            target_connections = set(self.active_connections.keys())

        # Remove excluded connections
        target_connections = target_connections - set(exclude)

        # Send to all targets
        sent_count = 0
        for connection_id in list(target_connections):
            if await self.send_to_connection(connection_id, data):
                sent_count += 1

        return sent_count

    async def broadcast_operation_update(
        self,
        operation_id: int,
        status: str,
        progress_percent: Optional[int] = None,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Broadcast operation progress update.

        Args:
            operation_id: Operation ID
            status: Operation status
            progress_percent: Progress percentage (0-100)
            message: Status message
            details: Additional details

        Returns:
            Number of connections notified
        """
        data = {
            "event_type": EventType.OPERATION_UPDATE.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "operation_id": operation_id,
                "status": status,
                "progress_percent": progress_percent,
                "message": message,
                "details": details or {},
            },
        }

        return await self.broadcast(data, topic=f"operation:{operation_id}")

    async def broadcast_worker_status(
        self,
        worker_id: int,
        worker_name: str,
        old_status: str,
        new_status: str,
        reason: Optional[str] = None,
    ) -> int:
        """
        Broadcast worker status change.

        Args:
            worker_id: Worker ID
            worker_name: Worker name
            old_status: Previous status
            new_status: New status
            reason: Reason for status change

        Returns:
            Number of connections notified
        """
        data = {
            "event_type": EventType.WORKER_STATUS.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "worker_id": worker_id,
                "worker_name": worker_name,
                "old_status": old_status,
                "new_status": new_status,
                "reason": reason,
            },
        }

        return await self.broadcast(data, topic="workers")

    async def broadcast_system_alert(
        self,
        severity: str,
        title: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Broadcast system alert.

        Args:
            severity: Alert severity (info, warning, error, critical)
            title: Alert title
            message: Alert message
            details: Additional details

        Returns:
            Number of connections notified
        """
        data = {
            "event_type": EventType.SYSTEM_ALERT.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "severity": severity,
                "title": title,
                "message": message,
                "details": details or {},
            },
        }

        return await self.broadcast(data, topic="alerts")

    async def broadcast_log_entry(
        self,
        log_level: str,
        action: str,
        user_id: Optional[int],
        username: Optional[str],
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Broadcast new log entry.

        Args:
            log_level: Log level
            action: Action performed
            user_id: User ID
            username: Username
            details: Additional details

        Returns:
            Number of connections notified
        """
        data = {
            "event_type": EventType.LOG_ENTRY.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "level": log_level,
                "action": action,
                "user_id": user_id,
                "username": username,
                "details": details or {},
            },
        }

        return await self.broadcast(data, topic="logs")

    async def _heartbeat_loop(self):
        """Send periodic heartbeat/ping to all connections."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Send heartbeat every 30 seconds

                if not self.active_connections:
                    continue

                heartbeat_data = {
                    "event_type": EventType.HEARTBEAT.value,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                # Send to all connections
                for connection_id in list(self.active_connections.keys()):
                    await self.send_to_connection(connection_id, heartbeat_data)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in heartbeat loop: {exc}")

    def get_connection_count(self) -> int:
        """Get number of active connections."""
        return len(self.active_connections)

    def get_topic_subscribers(self, topic: str) -> int:
        """Get number of subscribers for a topic."""
        return len(self.subscriptions.get(topic, set()))


# Global WebSocket manager instance
ws_manager = WebSocketManager()


async def get_ws_manager() -> WebSocketManager:
    """Dependency to get WebSocket manager instance."""
    return ws_manager
