import logging
import os
from dataclasses import dataclass, field
from enum import Enum as enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union, Iterable

from c2py.clang.cindex import (Config, Cursor, CursorKind, Diagnostic, Index, SourceLocation,
                                    Token, TokenKind, TranslationUnit, Type)
from c2py.core.core_types.cxx_types import is_const_type
from c2py.core.core_types.parser_types import AnyCxxSymbol, Class, Enum, FileLocation, \
    Function, \
    Location, Macro, Method, Namespace, TemplateClass, Typedef, Variable, AnonymousUnion
from c2py.core.utils import _try_parse_cpp_digit_literal

logger = logging.getLogger(__file__)

NAMESPACE_UNSUPPORTED_CURSORS = {
    # processed by other functions as child cursor
    CursorKind.ENUM_CONSTANT_DECL,
    CursorKind.CXX_METHOD,
    CursorKind.CXX_FINAL_ATTR,
    CursorKind.DESTRUCTOR,
    CursorKind.PARM_DECL,
    CursorKind.CXX_ACCESS_SPEC_DECL,
    CursorKind.CONSTRUCTOR,
    CursorKind.FIELD_DECL,
    # no need to parse
    CursorKind.COMPOUND_STMT,
    CursorKind.MACRO_INSTANTIATION,
    CursorKind.PAREN_EXPR,
    CursorKind.BINARY_OPERATOR,
    CursorKind.UNARY_OPERATOR,
    CursorKind.DLLIMPORT_ATTR,
    CursorKind.NAMESPACE_REF,
    CursorKind.STATIC_ASSERT,
    CursorKind.INCLUSION_DIRECTIVE,
    # not supported yet
    CursorKind.FUNCTION_TEMPLATE,
    CursorKind.USING_DECLARATION,
    # i don't know what those are
    CursorKind.UNEXPOSED_DECL,
    CursorKind.TYPE_REF,
    CursorKind.UNEXPOSED_EXPR,
    CursorKind.DECL_REF_EXPR,
}
CLASS_UNSUPPORTED_CURSORS = {
    # no need to pass
    CursorKind.CXX_ACCESS_SPEC_DECL,
    CursorKind.INIT_LIST_EXPR,
    CursorKind.MEMBER_REF,
    CursorKind.STATIC_ASSERT,
    CursorKind.FRIEND_DECL,

    # not supported yet
    CursorKind.FUNCTION_TEMPLATE,
    CursorKind.CONVERSION_FUNCTION,
    CursorKind.USING_DECLARATION,
    CursorKind.CXX_FINAL_ATTR,
    CursorKind.VAR_DECL,
    CursorKind.TEMPLATE_TEMPLATE_PARAMETER,
    CursorKind.TEMPLATE_TYPE_PARAMETER,
    CursorKind.TEMPLATE_NON_TYPE_PARAMETER,

    # don't know what these is
    CursorKind.DECL_REF_EXPR,
    CursorKind.TYPE_REF,
    CursorKind.PARM_DECL,
    CursorKind.UNEXPOSED_ATTR,
    CursorKind.TEMPLATE_REF,
    CursorKind.CONVERSION_FUNCTION,
    CursorKind.CXX_BOOL_LITERAL_EXPR,
    CursorKind.CALL_EXPR,
    CursorKind.CXX_STATIC_CAST_EXPR,
    CursorKind.CONDITIONAL_OPERATOR,
    CursorKind.PACK_EXPANSION_EXPR,
    CursorKind.UNEXPOSED_EXPR,
}

LITERAL_KINDS = {
    CursorKind.INTEGER_LITERAL,
    CursorKind.STRING_LITERAL,
    CursorKind.CHARACTER_LITERAL,
    CursorKind.CXX_NULL_PTR_LITERAL_EXPR,
    CursorKind.CXX_BOOL_LITERAL_EXPR,
    CursorKind.FLOATING_LITERAL,
    CursorKind.IMAGINARY_LITERAL,
    # CursorKind.OBJC_STRING_LITERAL,
    # CursorKind.OBJ_BOOL_LITERAL_EXPR,
    # CursorKind.COMPOUND_LITERAL_EXPR,
}

METHOD_UNSUPPORTED_CURSORS = {
    CursorKind.COMPOUND_STMT,  # function body

    # no need to parse
    CursorKind.TYPE_REF,
    CursorKind.PARM_DECL,
    CursorKind.NAMESPACE_REF,
    CursorKind.UNEXPOSED_ATTR,
    CursorKind.UNEXPOSED_EXPR,
    CursorKind.MEMBER_REF,
    CursorKind.INIT_LIST_EXPR,
    CursorKind.CXX_OVERRIDE_ATTR,
}


@dataclass()
class CXXParseResult:
    g: Namespace  # global namespace, cpp type tree starts from here
    macros: Dict[str, Macro] = field(default_factory=dict)
    objects: Dict[str, AnyCxxSymbol] = field(default_factory=dict)


def file_location_from_extend(e: SourceLocation):
    return FileLocation(line=e.line, column=e.column, offset=e.offset)


def location_from_cursor(c: Cursor):
    file = c.extent.start.file
    if file:
        return Location(file.name,
                        file_location_from_extend(c.extent.start),
                        file_location_from_extend(c.extent.end))
    return None


on_progress_type = Optional[Callable[[int, int], Any]]


class CxxStandard(enum):
    Cpp11 = '-std=c++11'
    Cpp14 = '-std=c++14'
    Cpp17 = '-std=c++17'
    Cpp20 = '-std=c++20'


class Arch(enum):
    X86 = "-m32"
    X64 = "-m64"


@dataclass()
class CXXParserExtraOptions:
    show_progress = True
    standard: CxxStandard = CxxStandard.Cpp17
    arch: Arch = Arch.X64


class CXXParser:

    def __init__(
        self,
        file_path: Optional[str],
        unsaved_files: Sequence[Sequence[str]] = None,
        args: List[str] = None,
        extra_options: CXXParserExtraOptions = None
    ):
        if extra_options is None:
            extra_options = CXXParserExtraOptions()
        if args is None:
            args = []
        self.unsaved_files = unsaved_files
        self.file_path = file_path
        self.args = args
        self.extra_options = extra_options

        self.args.append(extra_options.standard.value)
        self.args.append(extra_options.arch.value)

        self.unnamed_index = 0

        self.cursors: Dict = {}

        self.objects: Dict[str, AnyCxxSymbol] = {}

    def parse(self) -> CXXParseResult:
        idx = Index.create()
        rs = idx.parse(
            self.file_path,
            args=self.args,
            unsaved_files=self.unsaved_files,
            options=(
                TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD |
                TranslationUnit.PARSE_SKIP_FUNCTION_BODIES |  # important
                TranslationUnit.PARSE_INCLUDE_BRIEF_COMMENTS_IN_CODE_COMPLETION
            ),
        )
        for i in rs.diagnostics:
            if i.severity >= Diagnostic.Warning:
                logger.warning("%s", i)
        ns = Namespace(
            name='',
            parent=None,
            location=location_from_cursor(rs.cursor),
        )
        self._process_namespace(rs.cursor, ns, store_global=True, on_progress=self.on_progress)
        result = CXXParseResult(ns)

        for ac in rs.cursor.walk_preorder():
            # parse macros
            if ac.kind == CursorKind.MACRO_DEFINITION:
                m = CXXParser._process_macro_definition(ac)
                result.macros[m.name] = m
        result.objects = self.objects
        return result

    def on_progress(self, cur, total):
        if self.extra_options.show_progress:
            percent = float(cur) / total * 100
            print(f"\rparsing {percent:.2f}: {cur}/{total}", end='', flush=True)
            if cur == total:
                print("")

    def _process_namespace(self,
                           c: Cursor,
                           n: Namespace,
                           store_global: bool,
                           on_progress: on_progress_type = None,
                           ):
        """All result will append in parameter n"""
        n.location = location_from_cursor(c)
        self.objects[n.full_name] = n
        if c.kind == CursorKind.NAMESPACE and c.spelling:
            n.name = c.spelling
        children = list(c.get_children())
        count = len(children)

        passed = False

        for i, ac in enumerate(children):
            # log cursor kind
            if ac.kind != CursorKind.MACRO_DEFINITION:
                logger.debug("%s", ac.kind)
            if passed or ac.spelling == 'A':
                passed = True
                print(ac.kind)

            # skip macros
            if ac.kind == CursorKind.MACRO_DEFINITION:
                continue

            self._process_namespace_child(ac, n, store_global=store_global)
            if on_progress:
                on_progress(i + 1, count)
        return n

    def _process_namespace_child(self, ac: Cursor, n: Namespace, store_global: bool):
        # extern "C" {...}
        if ac.kind == CursorKind.UNEXPOSED_DECL:
            self._process_namespace(ac, n, store_global)
        # sub namespace
        elif ac.kind == CursorKind.NAMESPACE:
            sub_ns = Namespace(
                name=ac.spelling,
                parent=n,
                location=location_from_cursor(ac),
                brief_comment=ac.brief_comment,
            )
            self._process_namespace(ac, sub_ns, store_global)
            if sub_ns.name not in n.namespaces:
                n.namespaces[sub_ns.name] = sub_ns
            else:
                n.namespaces[sub_ns.name].extend(sub_ns)
        # function
        elif ac.kind == CursorKind.FUNCTION_DECL:
            func = self._process_function(ac, n, store_global=store_global)
            n.functions[func.name].append(func)
        # enum
        elif ac.kind == CursorKind.ENUM_DECL:
            e = self._process_enum(ac, n, store_global=store_global)
            e.parent = n
            n.enums[e.name] = e
        # class
        elif (
            ac.kind == CursorKind.CLASS_DECL
            or ac.kind == CursorKind.STRUCT_DECL
            or ac.kind == CursorKind.UNION_DECL
        ):
            class_ = self._process_class(ac, n, store_global=store_global)
            class_.parent = n
            n.classes[class_.name] = class_
        # class template
        # is just parsed as a class, no template variables will parsed
        elif (
            ac.kind == CursorKind.CLASS_TEMPLATE
            or ac.kind == CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION
        ):
            class_ = self._process_template_class(ac, n, store_global=store_global)
            class_.parent = n
            n.template_classes[class_.name] = class_
        # variable
        elif ac.kind == CursorKind.VAR_DECL:
            value = self._process_variable(ac, n, store_global=store_global)
            n.variables[value.name] = value
        elif (ac.kind == CursorKind.TYPEDEF_DECL
              or ac.kind == CursorKind.TYPE_ALIAS_DECL
        ):
            tp = self._process_typedef(ac, n, store_global=store_global)
            n.typedefs[tp.name] = tp
        elif ac.kind == CursorKind.TYPE_ALIAS_TEMPLATE_DECL:
            tp = self._process_template_alias(ac, n, store_global=store_global)
            n.typedefs[tp.name] = tp
        elif (ac.kind in NAMESPACE_UNSUPPORTED_CURSORS
              or self._is_literal_cursor(ac)):
            pass
        else:
            if ac.extent.start.file:
                logging.warning(
                    "unrecognized cursor kind: %s, spelling:%s, type:%s, %s",
                    ac.kind,
                    ac.type.spelling,
                    ac.spelling,
                    ac.extent,
                )

    def _process_function(self, c: Cursor, parent: Namespace, store_global: bool):
        func = Function(
            name=c.spelling,
            parent=parent,
            location=location_from_cursor(c),
            ret_type=c.result_type.spelling,
            args=[
                Variable(name=ac.spelling, type=ac.type.spelling)
                for ac in c.get_arguments()
            ],
            brief_comment=c.brief_comment,
        )
        if store_global:
            self.objects[func.full_name] = func
        return func

    def _process_method(self, c: Cursor, class_, store_global: bool):
        func = Method(
            parent=class_,
            name=c.spelling,
            location=location_from_cursor(c),
            ret_type=c.result_type.spelling,
            access=c.access_specifier.name.lower(),
            is_virtual=c.is_virtual_method(),
            is_pure_virtual=c.is_pure_virtual_method(),
            is_static=c.is_static_method(),
            brief_comment=c.brief_comment,
        )
        for ac in c.get_arguments():
            arg = self._process_variable(ac, class_, warn_failed=False, store_global=store_global)
            func.args.append(arg)
        for ac in c.get_children():
            if ac.kind == CursorKind.CXX_FINAL_ATTR:
                func.is_final = True
            elif ac.kind in METHOD_UNSUPPORTED_CURSORS:
                pass
            else:
                logger.warning(
                    "unknown kind in cxx_method child: %s %s",
                    ac.kind,
                    ac.extent,
                )
        if store_global:
            self.objects[func.full_name] = func
        return func

    def _process_class(self, c: Cursor, parent: AnyCxxSymbol, store_global: bool):
        # noinspection PyArgumentList
        name = c.spelling
        class_ = Class(name=name,
                       parent=parent,
                       location=location_from_cursor(c),
                       brief_comment=c.brief_comment,
                       )
        for ac in c.get_children():
            self._process_class_child(ac, class_, store_global=store_global)

        if store_global:
            self.objects[class_.full_name] = class_
        return class_

    def _process_union(self, c, scope_name, class_: Class, store_global: bool):
        if c.is_anonymous():
            union_type = AnonymousUnion(
                name=f'decltype({scope_name})',
                parent=class_,
                scope_name=scope_name,
                location=location_from_cursor(c),
                brief_comment=c.brief_comment,
            )
        else:
            union_type = self._process_class(c, parent=class_, store_global=store_global)
        for ac in c.get_children():
            self._process_class_child(ac, union_type, store_global=store_global)
        if store_global:
            self.objects[union_type.full_name] = union_type
        return union_type

    def _process_template_class(self, c: Cursor, parent: AnyCxxSymbol, store_global: bool):
        class_ = self._process_class(c, parent, False)
        class_ = TemplateClass(**class_.__dict__)
        class_.location = location_from_cursor(c)

        if store_global:
            self.objects[class_.full_name] = class_
        return class_

    @staticmethod
    def _union_scope_name(union_cursor: Cursor):
        """
        If this (anonymous) union type is scoped, return its scope name. Or return None.

        definition about scoped or not scoped can be found in tests/python_side/union.py
        checking method: a scoped anonymous type must be reference by a FIELD_DECL in its parent.
        :return: scope_name
        """
        pc = union_cursor.semantic_parent
        for ac in pc.get_children():
            if ac.kind == CursorKind.FIELD_DECL:
                if ac.type.get_named_type().spelling == union_cursor.type.spelling:
                    return ac.spelling
        return None

    def _process_class_child(self, ac: Cursor, class_: Class, store_global: bool):
        if ac.kind == CursorKind.CXX_BASE_SPECIFIER:
            super_name = self._qualified_name(ac)
            if super_name in self.objects:
                # if parent class is a template class, it will not be parsed
                s = self.objects[super_name]
                class_.super.append(s)
            else:
                pass
        elif ac.kind == CursorKind.CONSTRUCTOR:
            func = self._process_method(ac, class_, store_global=store_global)
            if func.is_virtual:
                class_.is_polymorphic = True
            class_.constructors.append(func)
        elif (ac.kind == CursorKind.CLASS_DECL
              or ac.kind == CursorKind.STRUCT_DECL
              or ac.kind == CursorKind.CLASS_TEMPLATE
              or ac.kind == CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION
        ):
            child = self._process_class(c=ac, parent=class_, store_global=store_global)
            class_.classes[child.name] = child
        elif ac.kind == CursorKind.UNION_DECL:
            # for type first
            scope_name = self._union_scope_name(ac)
            child = self._process_union(ac,
                                        scope_name,
                                        class_,
                                        store_global=True)
            anonymous = ac.is_anonymous()
            if scope_name and not anonymous:
                class_.classes[child.name] = child
                return
            if scope_name and anonymous:
                class_.classes[child.name] = child
                return
            if not scope_name and anonymous:
                class_.extend(child)
                return
            if not scope_name and not anonymous:
                class_.classes[child.name] = child
                class_.extend(child)
                return

        elif ac.kind == CursorKind.DESTRUCTOR:
            func = self._process_method(ac, class_, store_global=store_global)
            if func.is_virtual:
                class_.is_polymorphic = True
            class_.destructor = func
        elif ac.kind == CursorKind.ENUM_DECL:
            e = self._process_enum(ac, class_, store_global=store_global)
            class_.enums[e.name] = e
        elif ac.kind == CursorKind.FIELD_DECL:
            v = self._process_variable(ac, class_, store_global=store_global)
            class_.variables[v.name] = v
        elif ac.kind == CursorKind.CXX_METHOD:
            func = self._process_method(ac, class_, store_global=store_global)
            if func.is_virtual:
                class_.is_polymorphic = True
            class_.functions[func.name].append(func)
        elif (ac.kind == CursorKind.TYPEDEF_DECL
              or ac.kind == CursorKind.TYPE_ALIAS_DECL):
            tp = self._process_typedef(ac, class_, store_global=store_global)
            class_.typedefs[tp.name] = tp
        elif ac.kind == CursorKind.TYPE_ALIAS_TEMPLATE_DECL:
            tp = self._process_template_alias(ac, class_, store_global=store_global)
            class_.typedefs[tp.name] = tp
        elif ac.kind in CLASS_UNSUPPORTED_CURSORS:
            pass
        else:
            logger.warning(
                "unknown kind in class child, and not handled: %s %s",
                ac.kind,
                ac.extent,
            )

    def _process_enum(self, c: Cursor, parent: AnyCxxSymbol, store_global: bool):
        e = Enum(name=c.spelling,
                 parent=parent,
                 location=location_from_cursor(c),
                 type=c.enum_type.spelling,
                 is_strong_typed=c.is_scoped_enum(),
                 brief_comment=c.brief_comment,
                 )
        for i in list(c.get_children()):
            e.variables[i.spelling] = Variable(
                parent=e,
                name=i.spelling,
                location=location_from_cursor(i),
                type=e.name,
                value=i.enum_value,
                brief_comment=c.brief_comment,
            )
        if store_global:
            self.objects[e.full_name] = e
        return e

    def _process_variable(self,
                          c: Cursor,
                          parent: AnyCxxSymbol,
                          store_global: bool,
                          warn_failed: bool = True) -> (str, Optional[Variable]):
        type = c.type.spelling
        var = Variable(
            name=c.spelling,
            parent=parent,
            location=location_from_cursor(c),
            type=type,
            const=is_const_type(type),
            brief_comment=c.brief_comment,
        )
        literal, value = self._parse_literal_cursor(c, warn_failed)
        var.literal = literal
        var.value = value
        if store_global:
            self.objects[var.full_name] = var
        return var

    def _process_typedef(self, c: Cursor, ns: Namespace, store_global: bool):
        name = c.spelling
        target_cursor = c.underlying_typedef_type
        target_name: str = self._qualified_name(target_cursor)

        return self.save_typedef(c, ns, name, target_name, store_global=store_global)

    def _process_template_alias(self, c: Cursor, ns: Namespace, store_global: bool):
        name = c.spelling
        target_cursor = self._get_template_alias_target(c)
        target_name = self._qualified_name(target_cursor)

        return self.save_typedef(c, ns, name, target_name, store_global=store_global)

    def save_typedef(self, c: Cursor, ns: Namespace, name: str, target_name: str, store_global: bool):
        tp = Typedef(name=name,
                     target=target_name,
                     parent=ns,
                     location=location_from_cursor(c),
                     brief_comment=c.brief_comment,
                     )
        if store_global:
            self.objects[tp.full_name] = tp
        ns.typedefs[tp.name] = tp
        return tp

    @staticmethod
    def _process_macro_definition(c: Cursor):
        name = c.spelling
        tokens = list(c.get_tokens())
        length = len(tokens)
        m = Macro(name=name,
                  parent=None,  # macro has no parent
                  location=location_from_cursor(c),
                  definition="",
                  brief_comment=c.brief_comment,
                  )
        if length == 1:
            return m
        m.definition = " ".join([i.spelling for i in tokens[1:]])
        return m

    def _qualified_name(self, c: Union[Type, Cursor]):
        # if c.kind == CursorKind.
        if isinstance(c, Cursor):
            return self._qualified_cursor_name(c)
        elif isinstance(c, Type):
            d = c.get_declaration()
            if d.kind != CursorKind.NO_DECL_FOUND:
                return self._qualified_name(d)
        return c.spelling

    def _qualified_cursor_name(self, c):
        if c.semantic_parent:
            if (c.semantic_parent.kind == CursorKind.NAMESPACE
                or c.semantic_parent.kind == CursorKind.CLASS_DECL
            ):
                return self._qualified_name(c.semantic_parent) + "::" + c.spelling
        return "::" + c.spelling

    def _get_template_alias_target(self, c: Cursor):
        children = list(c.get_children())
        for child in children:
            if child.kind == CursorKind.TYPE_ALIAS_DECL:
                return child.underlying_typedef_type
        return None

    @staticmethod
    def _get_source_from_file(file, start, end, encoding="utf-8"):
        with open(file, "rb") as f:
            f.seek(start)
            return f.read(end - start).decode(encoding=encoding)

    @staticmethod
    def _get_source(token: Token, encoding="utf-8"):
        return CXXParser._get_source_from_file(
            token.location.file.name,
            token.extent.start.offset,
            token.extent.end.offset,
            encoding,
        )

    @staticmethod
    def _is_literal_cursor(c: Cursor):
        return c.kind in LITERAL_KINDS

    def _try_parse_literal(self, cursor_kind: CursorKind, spelling: str) \
        -> Optional[Union[str, float, int]]:
        """
        used to parse direct variable definition or some variable initialized by macro
        """
        if cursor_kind == CursorKind.INTEGER_LITERAL:
            return _try_parse_cpp_digit_literal(spelling).value
        elif cursor_kind == CursorKind.STRING_LITERAL:
            return str(spelling)
        elif cursor_kind == CursorKind.CHARACTER_LITERAL:
            return CXXParser.character_literal_to_int(spelling)
        elif cursor_kind == CursorKind.FLOATING_LITERAL:
            return float(spelling)
        else:
            logger.warning(
                "unknown literal kind:%s", cursor_kind
            )
            return None

    def _parse_macro_literal_cursor(self, c: Cursor):
        """
        parse macro instantiation cursor.
        :param c:
        :return:
        """
        for child in c.walk_preorder():
            if self._is_literal_cursor(child):
                tokens = [t for t in child.get_tokens()]
                for t in tokens:
                    if t.kind == TokenKind.LITERAL:
                        return t.spelling, self._try_parse_literal(child.kind, t.spelling)

    def _parse_literal_cursor(self, c: Cursor, warn_failed: bool = False) \
        -> Tuple[Optional[str], Optional[Union[str, float, int]]]:
        """
        used to parse variable
        :return: literal, value
        """
        tokens: List[Token] = list(c.get_tokens())
        has_assign = False
        for i, t in enumerate(tokens):
            if has_assign:
                if t.kind == TokenKind.IDENTIFIER:
                    if t.cursor.kind == CursorKind.MACRO_INSTANTIATION:
                        return self._parse_macro_literal_cursor(c)
                if t.kind == TokenKind.LITERAL:
                    spelling = t.spelling
                    val = self._try_parse_literal(t.cursor.kind, t.spelling)
                    last_t = tokens[i - 1]
                    if last_t.kind == TokenKind.PUNCTUATION and last_t.spelling == '-':
                        return spelling, -val
                    return spelling, val
            elif t.spelling == '=':
                has_assign = True
        if has_assign:
            if warn_failed:
                logger.warning(
                    "unknown literal, kind:%s, spelling:%s, %s", c.kind, c.spelling, c.extent
                )
        return None, None

    @staticmethod
    def character_literal_to_int(string):
        s = 0
        for i in string.encode():
            s = s * 255 + i
        return s

    pass


def seek_file(file: str, paths: Iterable[str], allow_dir: bool=False):
    for path in ["./", *paths]:
        final_path = os.path.join(path, file)
        if os.path.exists(final_path):
            if os.path.isdir(final_path):
                if allow_dir:
                    return final_path
            else:
                return final_path


class CxxFileParser(CXXParser):

    def __init__(
        self,
        files: Sequence[str],
        encoding: str = 'utf-8',
        include_paths: Sequence[str] = None,
        args: List[str] = None,
        extra_options: CXXParserExtraOptions = None
    ):
        unsaved_files = []
        if encoding != 'utf-8':
            for filepath in files:
                real_path = seek_file(filepath, include_paths)
                with open(real_path, 'rt', encoding=encoding) as f:
                    data = f.read()
                    unsaved_files.append([real_path, data.encode()])

        if args is None:
            args = []
        if include_paths:
            for include_path in include_paths:
                args.append("-I" + include_path)
        dummy_code = ""
        for file in files:
            dummy_code += f'#include "{file}"\n'

        dummy_name = "dummy.cpp"

        super().__init__(
            dummy_name, unsaved_files=[
                [dummy_name, dummy_code],
                *unsaved_files
            ],
            args=args,
            extra_options=extra_options,
        )


mydir = os.path.split(os.path.abspath(__file__))[0]
template_dir = os.path.join(mydir, "templates")
include_dir = os.path.join(mydir, "include")
Config.set_library_path(os.path.join(mydir, "../", "clang"))
