from datetime import datetime
from typing import Dict, Any, List, Optional
import uuid


# 内存存储笔记（演示用）
_notes_storage: Dict[str, Dict[str, Any]] = {}


async def create_note(title: str, content: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    创建新笔记
    
    Args:
        title: 笔记标题
        content: 笔记内容
        tags: 标签列表
        
    Returns:
        创建的笔记
    """
    note_id = str(uuid.uuid4())
    now = datetime.now()
    
    note = {
        "id": note_id,
        "title": title,
        "content": content,
        "tags": tags or [],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    }
    
    _notes_storage[note_id] = note
    
    return {
        "success": True,
        "note": note,
        "note_id": note_id
    }


async def get_note(note_id: str) -> Dict[str, Any]:
    """
    获取指定笔记
    
    Args:
        note_id: 笔记ID
        
    Returns:
        笔记信息
    """
    note = _notes_storage.get(note_id)
    
    if note:
        return {
            "success": True,
            "note": note
        }
    else:
        return {
            "success": False,
            "message": "笔记不存在"
        }


async def search_notes(keyword: Optional[str] = None, tag: Optional[str] = None) -> Dict[str, Any]:
    """
    搜索笔记
    
    Args:
        keyword: 搜索关键词
        tag: 标签过滤
        
    Returns:
        搜索结果
    """
    results = []
    
    for note in _notes_storage.values():
        match = True
        
        if keyword:
            if keyword not in note["title"] and keyword not in note["content"]:
                match = False
        
        if tag and tag not in note["tags"]:
            match = False
        
        if match:
            results.append(note)
    
    # 按更新时间排序
    results.sort(key=lambda x: x["updated_at"], reverse=True)
    
    return {
        "success": True,
        "count": len(results),
        "notes": results
    }


async def update_note(
    note_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    更新笔记
    
    Args:
        note_id: 笔记ID
        title: 新标题
        content: 新内容
        tags: 新标签
        
    Returns:
        更新后的笔记
    """
    if note_id not in _notes_storage:
        return {
            "success": False,
            "message": "笔记不存在"
        }
    
    note = _notes_storage[note_id]
    
    if title is not None:
        note["title"] = title
    
    if content is not None:
        note["content"] = content
    
    if tags is not None:
        note["tags"] = tags
    
    note["updated_at"] = datetime.now().isoformat()
    
    return {
        "success": True,
        "note": note
    }


async def delete_note(note_id: str) -> Dict[str, Any]:
    """
    删除笔记
    
    Args:
        note_id: 笔记ID
        
    Returns:
        删除结果
    """
    if note_id in _notes_storage:
        del _notes_storage[note_id]
        return {
            "success": True,
            "message": "笔记已删除"
        }
    else:
        return {
            "success": False,
            "message": "笔记不存在"
        }


async def list_notes(limit: int = 10) -> Dict[str, Any]:
    """
    列出所有笔记
    
    Args:
        limit: 数量限制
        
    Returns:
        笔记列表
    """
    notes = list(_notes_storage.values())
    
    # 按更新时间排序
    notes.sort(key=lambda x: x["updated_at"], reverse=True)
    
    # 限制数量
    notes = notes[:limit]
    
    return {
        "success": True,
        "count": len(notes),
        "total_count": len(_notes_storage),
        "notes": notes
    }
