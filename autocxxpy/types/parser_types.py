from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass(repr=0)
class FileLocation:
    offset: int = 0
    line: int = 0
    column: int = 0


@dataclass(repr=False)
class Location:
    file: Optional[str] = None
    start: Optional[FileLocation] = None
    end: Optional[FileLocation] = None


@dataclass(repr=False)
class Symbol:
    name: str = ""
    parent: Optional["AnyCxxSymbol"] = None
    location: Location = None

    @property
    def full_name(self):
        if self.parent is None:
            return f"{self.name}"
        return f'{self.parent.full_name}::{self.name}'


@dataclass(repr=False)
class Macro(Symbol):
    definition: str = ""


@dataclass(repr=False)
class Typedef(Symbol):
    target: str = ""


@dataclass(repr=False)
class Variable(Symbol):
    type: str = ""
    const: bool = False
    static: bool = False
    value: Any = None
    literal: str = None


@dataclass(repr=False)
class Enum(Symbol):
    type: str = ""
    parent: Optional["AnyCxxSymbol"] = None
    values: Dict[str, Variable] = field(default_factory=dict)
    is_strong_typed: bool = False


@dataclass(repr=False)
class Function(Symbol):
    ret_type: str = ""
    parent: Optional["Namespace"] = None
    args: List[Variable] = field(default_factory=list)
    calling_convention: str = "__cdecl"

    @property
    def type(self, show_calling_convention: bool = False):
        args = ",".join([i.type for i in self.args])
        calling = (
            self.calling_convention + " " if show_calling_convention else ""
        )
        return f"{self.ret_type}({calling} *)({args})"

    @property
    def signature(self):
        s = f"{self.name} ("
        for arg in self.args:
            s += arg.type + " " + arg.name + ","
        s = s[:-2] + ")"
        return s

    def __str__(self):
        return self.signature


@dataclass(repr=False)
class Namespace(Symbol):
    parent: Optional["Namespace"] = None
    enums: Dict[str, Enum] = field(default_factory=dict)
    typedefs: Dict[str, Typedef] = field(default_factory=dict)
    classes: Dict[str, "Class"] = field(default_factory=dict)
    template_classes: Dict[str, "TemplateClass"] = field(default_factory=dict)
    variables: Dict[str, Variable] = field(default_factory=dict)
    functions: Dict[str, List[Function]] = field(
        default_factory=(lambda: defaultdict(list))
    )
    namespaces: Dict[str, "Namespace"] = field(
        default_factory=lambda: defaultdict(lambda: Namespace()))

    def extend(self, other: "Namespace"):
        self.enums.update(other.enums)
        self.typedefs.update(other.typedefs)
        self.classes.update(other.classes)
        self.variables.update(other.variables)
        self.functions.update(other.functions)
        self.namespaces.update(other.namespaces)


@dataclass(repr=False)
class Class(Namespace):
    parent: Optional["AnyCxxSymbol"] = None
    super: List["Class"] = field(default_factory=list)
    functions: Dict[str, List["Method"]] = field(
        default_factory=(lambda: defaultdict(list))
    )
    constructors: List["Method"] = field(default_factory=list)
    destructor: "Method" = None

    is_polymorphic: bool = False

    def __str__(self):
        return "class " + self.name


@dataclass(repr=False)
class TemplateClass(Class):
    pass


@dataclass(repr=False)
class Method(Function):
    ret_type: str = ''
    parent: Class = None
    access: str = "public"
    is_virtual: bool = False
    is_pure_virtual: bool = False
    is_static: bool = False
    is_final: bool = False

    @property
    def type(self, show_calling_convention: bool = False):
        args = ",".join([i.type for i in self.args])
        calling = (
            self.calling_convention + " " if show_calling_convention else ""
        )
        parent_prefix = ""
        if not self.is_static:
            parent_prefix = f"{self.parent.full_name}::"
        return f"{self.ret_type}({calling}{parent_prefix}*)({args})"

    @property
    def signature(self):
        return (
            "{} {}{} {}::".format(
                self.access,
                "virtual" if self.is_virtual else "",
                "static" if self.is_static else "",
                self.parent.name,
            ) +
            super().signature +
            (" = 0" if self.is_pure_virtual else "")
        )

    def __str__(self):
        return self.signature


AnyCxxSymbol = Union[Enum,
                     Namespace,
                     Class,
                     Method,
                     Function,
                     Variable,
                     Typedef,
                     Macro,
                     Symbol]
