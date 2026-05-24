
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from app.core import logger
from app.core.models import Message as DBMessage
from app.core.models import ChatSession


class HistoryManager:
    """情景历史管理器"""
    
    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
    
    async def get_recent_messages(
        self,
        limit: int = 20,
        session_id: Optional[str] = None
    ) -> List[DBMessage]:
        """获取最近的消息"""
        query = select(DBMessage)
        
        if session_id:
            # 指定会话的消息
            query = query.where(DBMessage.session_id == session_id)
        else:
            # 所有会话的消息（关联用户会话）
            query = query.join(
                ChatSession, DBMessage.session_id == ChatSession.id
            ).where(ChatSession.user_id == self.user_id)
        
        query = query.order_by(desc(DBMessage.created_at)).limit(limit)
        result = await self.db.execute(query)
        messages = list(result.scalars().all())
        
        # 恢复时间顺序
        return list(reversed(messages))
    
    async def get_messages_by_session(
        self,
        session_id: str,
        limit: Optional[int] = None
    ) -> List[DBMessage]:
        """获取指定会话的消息"""
        query = select(DBMessage).where(
            DBMessage.session_id == session_id
        ).order_by(DBMessage.created_at)
        
        if limit:
            query = query.limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def search_messages(
        self,
        keyword: str,
        limit: int = 10
    ) -> List[DBMessage]:
        """搜索包含关键词的消息"""
        # 简单的字符串匹配搜索
        query = select(DBMessage).join(
            ChatSession, DBMessage.session_id == ChatSession.id
        ).where(
            ChatSession.user_id == self.user_id,
            DBMessage.content.ilike(f"%{keyword}%")
        ).order_by(desc(DBMessage.created_at)).limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def to_context_string(
        self,
        session_id: Optional[str] = None,
        limit: int = 10
    ) -> str:
        """转换为上下文字符串"""
        messages = await self.get_recent_messages(limit=limit, session_id=session_id)
        if not messages:
            return ""
        
        lines = ["【对话历史】"]
        for msg in messages:
            role = "用户" if msg.role == "user" else "助手"
            if len(msg.content) > 100:
                content = msg.content[:100] + "..."
            else:
                content = msg.content
            lines.append(f"{role}: {content}")
        
        return "\n".join(lines)
