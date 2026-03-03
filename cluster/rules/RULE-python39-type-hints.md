# RULE: Python 3.9 Type Hint Syntax

**Created:** 2026-03-02
**Trigger:** Writing type annotations in any `.py` file in the cluster
**Source mistake:** LESSON-2026-03-02 — used `List[X] | None` which crashes on Python 3.9

## The Problem

Python 3.10+ allows `X | Y` union syntax in type hints at runtime:
```python
def foo(x: list[str] | None = None):  # CRASHES on 3.9
```

CHARLIE runs macOS system Python **3.9.6**. This syntax raises:
```
TypeError: unsupported operand type(s) for |: '_GenericAlias' and 'NoneType'
```

The error happens **at import time**, not at call time — it breaks the entire module.

## The Rule

**When writing type hints in any Python file in this repo:**

1. **Use `Optional[X]` instead of `X | None`**
   ```python
   # WRONG — crashes on 3.9
   def foo(items: list[str] | None = None): ...

   # RIGHT
   from typing import Optional, List
   def foo(items: Optional[List[str]] = None): ...
   ```

2. **Use `Union[X, Y]` instead of `X | Y`**
   ```python
   # WRONG
   def bar(value: int | str): ...

   # RIGHT
   from typing import Union
   def bar(value: Union[int, str]): ...
   ```

3. **Use `typing` generics instead of builtin generics in annotations**
   ```python
   # WRONG — crashes on 3.9 without __future__
   def baz(items: list[str], mapping: dict[str, int]): ...

   # RIGHT (option A) — import from typing
   from typing import List, Dict
   def baz(items: List[str], mapping: Dict[str, int]): ...

   # RIGHT (option B) — use __future__ annotations
   from __future__ import annotations
   def baz(items: list[str], mapping: dict[str, int]): ...
   ```

4. **`from __future__ import annotations` is acceptable** — it makes all annotations strings (lazy evaluation), so `X | Y` and `list[str]` won't crash. But it must be the **first import** in the file.

## Quick Check

Before committing any `.py` file, scan for:
- `| None` in a type annotation (not inside a string or comment)
- `X | Y` union syntax outside of `TYPE_CHECKING` blocks
- Bare `list[`, `dict[`, `tuple[`, `set[` in annotations without `from __future__ import annotations`

## Scope

Applies to **all Python files** across the cluster. CHARLIE is 3.9.6, Pi edge node may be 3.9+, and we don't control what version ships on every node.
