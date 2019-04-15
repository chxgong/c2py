# encoding: utf-8
"""
type traits
"""
import functools
import re

from autocxxpy.core.types.parser_types import Function, Variable

_REMOVE_POINTER_RE = re.compile("[ \t]*\\*[ \t]*")
_FUNCTION_POINTER_RE = re.compile("(\\w+) +\\((\\w*)\\*(\\w*)\\)\\((.*)\\)")


@functools.lru_cache()
def is_const_type(t: str):
    if is_pointer_type(t):
        return t.endswith("const")
    return t.startswith('const ')


@functools.lru_cache()
def is_array_type(t: str):
    if is_std_vector(t):
        return True
    return t.endswith(']')


@functools.lru_cache()
def is_std_vector(t: str):
    return t.startswith("std::vector<")


@functools.lru_cache()
def is_pointer_type(t: str):
    """
    check if t is a T *
    """
    return remove_cvref(t).endswith('*')


@functools.lru_cache()
def is_reference_type(t: str):
    return "&" in t


@functools.lru_cache()
def is_function_pointer_type(t: str):
    # int32 (__cdecl*name)(OesApiSessionInfoT *, SMsgHeadT *, void *, OesQryCursorT *, void *)
    return _FUNCTION_POINTER_RE.match(t)


@functools.lru_cache()
def pointer_base(t: str):
    t = remove_cvref(t)
    return t[:-1].strip()


@functools.lru_cache()
def reference_base(t: str):
    return remove_cvref(t)


@functools.lru_cache()
def array_base(t: str):
    """
    :raise ValueError if t is not a array type
    """
    if is_std_vector(t):
        t = t[12:-1]
    else:
        t = t[: t.rindex("[")]
    return t.strip()


@functools.lru_cache()
def array_count_str(t: str):
    t = t[t.rindex("[") + 1:]
    t = t[:-1]
    return t


@functools.lru_cache()
def array_count(t: str):
    """
    :return: array_count, 0 if no count in this type.
    """
    t = array_count_str(t)
    if t:
        return int(t)
    return 0


@functools.lru_cache()
def function_pointer_type_info(t: str) -> Function:
    m = _FUNCTION_POINTER_RE.match(t)
    if m:
        ret_type = m.group(1)
        calling_convention = m.group(2)
        args_str = m.group(4)

        func = Function(
            name=m.group(3),
            ret_type=ret_type,
            calling_convention=calling_convention if calling_convention else None
        )
        func.args = [
            Variable(name='', type=arg.strip(), parent=func)
            for arg in args_str.split(',')
        ]
        return func


@functools.lru_cache()
def remove_cvref(t: str):
    if t.endswith(" const"):
        t = t[:-6]
    if t.endswith("const"):
        t = t[:-5]
    return (
        t.replace("const ", "")
            .replace("volatile ", "")
            .replace("&", "")
            .strip()
    )
