from typing import Any, Dict


async def add(a: float, b: float) -> Dict[str, Any]:
    return {
        "operation": "add",
        "a": a,
        "b": b,
        "result": a + b,
    }


async def subtract(a: float, b: float) -> Dict[str, Any]:
    return {
        "operation": "subtract",
        "a": a,
        "b": b,
        "result": a - b,
    }


async def multiply(a: float, b: float) -> Dict[str, Any]:
    return {
        "operation": "multiply",
        "a": a,
        "b": b,
        "result": a * b,
    }


async def divide(a: float, b: float) -> Dict[str, Any]:
    if b == 0:
        return {
            "operation": "divide",
            "a": a,
            "b": b,
            "error": "Division by zero is not allowed.",
        }
    return {
        "operation": "divide",
        "a": a,
        "b": b,
        "result": a / b,
    }
