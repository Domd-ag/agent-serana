from typing import Dict, Any, List
import json
import base64
import re
from collections import Counter


async def text_stats(text: str) -> Dict[str, Any]:
    """
    文本统计分析
    
    Args:
        text: 要分析的文本
        
    Returns:
        统计结果
    """
    # 字符统计
    char_count = len(text)
    word_count = len(text.split())
    line_count = len(text.splitlines())
    
    # 中英文分开统计
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    chinese_count = len(chinese_chars)
    english_chars = re.findall(r'[a-zA-Z]', text)
    english_count = len(english_chars)
    
    # 数字统计
    numbers = re.findall(r'\d', text)
    number_count = len(numbers)
    
    # 空格和标点统计
    whitespace_count = text.count(' ')
    punctuation_count = len(re.findall(r'[^\w\s]', text))
    
    # 句子统计（简单实现）
    sentences = re.split(r'[.!?。！？]+', text)
    sentence_count = len([s for s in sentences if s.strip()])
    
    return {
        "characters": char_count,
        "words": word_count,
        "sentences": sentence_count,
        "lines": line_count,
        "chinese_chars": chinese_count,
        "english_chars": english_count,
        "numbers": number_count,
        "whitespaces": whitespace_count,
        "punctuations": punctuation_count,
        "avg_word_length": round(len(text.replace(' ', '')) / word_count, 2) if word_count > 0 else 0
    }


async def json_pretty(json_str: str, indent: int = 2) -> Dict[str, Any]:
    """
    美化JSON格式
    
    Args:
        json_str: JSON字符串
        indent: 缩进空格数
        
    Returns:
        美化后的JSON
    """
    try:
        data = json.loads(json_str)
        pretty = json.dumps(data, indent=indent, ensure_ascii=False)
        
        return {
            "success": True,
            "original": json_str,
            "formatted": pretty,
            "data": data
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "JSON格式错误"
        }


async def extract_keywords(text: str, limit: int = 5) -> Dict[str, Any]:
    """
    提取关键词（简单实现，基于词频）
    
    Args:
        text: 文本内容
        limit: 返回数量限制
        
    Returns:
        关键词列表
    """
    # 简单分词（按空格和标点）
    words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', text.lower())
    
    # 过滤停用词
    stopwords = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
                 'the', 'a', 'an', 'and', 'or', 'but', 'is', 'are', 'was', 'were', 'be', 'been',
                 'will', 'would', 'can', 'could', 'should', 'may', 'might', 'must', 'shall',
                 'for', 'from', 'in', 'on', 'at', 'by', 'with', 'about', 'like', 'to', 'of'}
    
    filtered = [w for w in words if w not in stopwords and len(w) > 1]
    
    # 统计词频
    word_freq = Counter(filtered)
    
    # 获取高频词
    keywords = [word for word, freq in word_freq.most_common(limit)]
    
    return {
        "success": True,
        "keywords": keywords,
        "total_words": len(words),
        "unique_words": len(word_freq)
    }


async def word_frequency(text: str, limit: int = 10) -> Dict[str, Any]:
    """
    词频统计
    
    Args:
        text: 文本内容
        limit: 返回数量限制
        
    Returns:
        词频统计结果
    """
    # 分词
    words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', text.lower())
    
    # 统计词频
    word_freq = Counter(words)
    
    # 获取高频词
    top_words = [
        {"word": word, "count": count}
        for word, count in word_freq.most_common(limit)
    ]
    
    return {
        "success": True,
        "total_words": len(words),
        "unique_words": len(word_freq),
        "top_words": top_words
    }


async def base64_encode(text: str) -> Dict[str, Any]:
    """
    Base64编码
    
    Args:
        text: 要编码的文本
        
    Returns:
        编码结果
    """
    try:
        b64_bytes = base64.b64encode(text.encode('utf-8'))
        b64_str = b64_bytes.decode('utf-8')
        
        return {
            "success": True,
            "original": text,
            "encoded": b64_str
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


async def base64_decode(b64_str: str) -> Dict[str, Any]:
    """
    Base64解码
    
    Args:
        b64_str: 要解码的Base64字符串
        
    Returns:
        解码结果
    """
    try:
        decoded_bytes = base64.b64decode(b64_str)
        decoded = decoded_bytes.decode('utf-8')
        
        return {
            "success": True,
            "original": b64_str,
            "decoded": decoded
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Base64解码失败"
        }
