import logging
import os
from copy import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from .cxxparser import LiteralVariable
from .preprocessor import GeneratorClass, GeneratorEnum, GeneratorFunction, GeneratorMethod, \
    GeneratorVariable, PreProcessorResult, GeneratorNamespace, GeneratorLiteralVariable
from .textholder import Indent, IndentLater, TextHolder
from .type import (array_base, function_type_info, is_array_type, is_function_type, is_pointer_type,
                   pointer_base, remove_cvref)

logger = logging.getLogger(__file__)


def _read_file(name: str):
    with open(name, "rt") as f:
        return f.read()


def render_template(template: str, **kwargs):
    for key, replacement in kwargs.items():
        template = template.replace(f"${key}", str(replacement))
    return template


@dataclass
class GeneratorOptions(GeneratorNamespace):
    dict_classes: Set[str] = field(default_factory=set)  # to dict, not used currently
    includes: List[str] = field(default_factory=list)
    caster_class: GeneratorClass = None

    arithmetic_enum: bool = True
    export_enums: bool = True
    split_in_files: bool = True
    module_name: str = "unknown_module"
    max_classes_in_one_file: int = 50
    constants_in_class: str = "constants"

    @staticmethod
    def from_preprocessor_result(
        module_name: str,
        res: PreProcessorResult,
        const_macros_as_variable: bool = True,
        ignore_global_variables_starts_with_underline: bool = True,
        **kwargs,
    ):
        variables = copy(res.variables)
        if const_macros_as_variable:
            variables.update(res.const_macros)

        if ignore_global_variables_starts_with_underline:
            variables = {
                k: v for k, v in variables.items() if not k.startswith("_")
            }

        return GeneratorOptions(
            module_name=module_name,

            typedefs=res.typedefs,
            variables=variables,
            functions=res.functions,
            classes=res.classes,
            dict_classes=res.dict_classes,
            enums=res.enums,
            caster_class=res.caster_class,

            **kwargs
        )


cpp_str_bases = {"char", "wchar_t", "char8_t", "char16_t", "char32_t"}
cpp_base_type_to_python_map = {
    "char8_t": "int",
    "char16_t": "int",
    "char32_t": "int",
    "wchar_t": "int",
    "char": "int",
    "short": "int",
    "int": "int",
    "long": "int",
    "long long": "int",
    "signed char": "int",
    "signed short": "int",
    "signed int": "int",
    "signed long": "int",
    "signed long long": "int",
    "unsigned char": "int",
    "unsigned short": "int",
    "unsigned int": "int",
    "unsigned long": "int",
    "unsigned long long": "int",
    "float": "float",
    "double": "float",
    "bool": "bool",
    "void": "Any",
}
python_type_to_pybind11 = {
    "int": "int_",
    "float": "float_",
    "str": "str",
    "None": "none",
}


def cpp_base_type_to_python(ot: str):
    t = remove_cvref(ot)
    if is_pointer_type(t):
        if pointer_base(t) in cpp_str_bases:
            return "str"
    if is_array_type(t):
        if array_base(t) in cpp_str_bases:
            return "str"
    if t in cpp_base_type_to_python_map:
        return cpp_base_type_to_python_map[t]
    return None


def cpp_base_type_to_pybind11(t: str):
    t = remove_cvref(t)
    return python_type_to_pybind11[cpp_base_type_to_python(t)]


def python_value_to_cpp_literal(val: Any):
    t = type(val)
    if t is str:
        return f'"({val})"'
    if t is int:
        return f"({val})"
    if t is float:
        return f"(double({val}))"


@dataclass
class GeneratorResult:
    saved_files: Dict[str, str] = None

    def output(self, output_dir: str, clear:bool = False):
        # clear output dir
        if not os.path.exists(output_dir):
            os.mkdir(output_dir)
        self.clear_dir(output_dir)

        for name, data in self.saved_files.items():
            with open(f"{output_dir}/{name}", "wt") as f:
                f.write(data)

    @staticmethod
    def clear_dir(path: str):
        for file in os.listdir(path):
            os.unlink(os.path.join(path, file))


class Generator:

    def __init__(self, options: GeneratorOptions):
        self.options = options
        self.module_tag = 'tag_' + options.module_name.lower()

        mydir = os.path.split(os.path.abspath(__file__))[0]
        self.template_dir = os.path.join(mydir, "templates")

        self.saved_files: Dict[str, str] = {}

    def generate(self):

        # all classes
        self._output_wrappers()
        self._output_module()
        self._output_class_generator_declarations()

        self._output_ide_hints()

        self._save_template(
            'module.hpp',
            module_tag=self.module_tag,
        )

        return GeneratorResult(self.saved_files)

    def cpp_variable_to_py_with_hint(
        self, v: GeneratorVariable, append="", append_unknown: bool = True
    ):
        cpp_type = self.cpp_type_to_python(v.type)
        default_value = ""
        if v.default:
            val = v.default
            exp = str(val)
            t = type(val)
            if t is str:
                exp = f'"""{val}"""'
            default_value = ' = ' + exp
        if cpp_type:
            return f"{v.alias}: {cpp_type}{default_value}{append}"
        if append_unknown:
            return f"{v.alias}: {v.type}{default_value}{append}  # unknown what to wrap in py"
        else:
            return f"{v.alias}: {v.type}{default_value}{append}"

    def cpp_type_to_python(self, t: str):
        t = remove_cvref(t)
        if t.startswith('struct '):
            return self.cpp_type_to_python(t[7:])
        base_type = cpp_base_type_to_python(t)
        if base_type:
            return base_type
        if is_function_type(t):
            func = function_type_info(t)
            args = ",".join([self.cpp_type_to_python(arg.type) for arg in func.args])
            return f'Callable[[{args}], {self.cpp_type_to_python(func.ret_type)}]'
        if is_pointer_type(t):
            return self.cpp_type_to_python(pointer_base(t))
        if is_array_type(t):
            base = self.cpp_type_to_python(array_base(t))
            return f'Sequence[{base}]'

        # check classes
        if t in self.options.classes:
            c = self.options.classes[t]
            if self._should_wrap_as_dict(c):
                return "dict"
            else:
                return t

        # check enums
        if t in self.options.enums:
            return t

        if t in self.options.typedefs:
            return self.cpp_type_to_python(self.options.typedefs[t])

        return cpp_base_type_to_python(t)

    def _should_wrap_as_dict(self, c: GeneratorClass):
        return c.name in self.options.dict_classes

    def _generate_hint_for_class(self, c: GeneratorClass):
        class_code = TextHolder()
        class_code += f"class {c.name}:" + Indent()
        for ms in c.functions.values():
            for m in ms:
                class_code += "\n"
                if m.is_static:
                    class_code += "@staticmethod"
                    class_code += f"def {m.alias}(" + Indent()
                else:
                    class_code += f"def {m.alias}(self, " + Indent()

                for arg in m.args:
                    class_code += Indent(
                        self.cpp_variable_to_py_with_hint(
                            arg, append=","
                        )
                    )
                cpp_ret_type = self.cpp_type_to_python(m.ret_type)
                class_code += f") -> {cpp_ret_type if cpp_ret_type else m.ret_type}:"
                class_code += "..." - IndentLater()
                class_code += "\n"

        for v in c.variables.values():
            description = self.cpp_variable_to_py_with_hint(v)
            class_code += f"{description}"

        class_code += "..." - IndentLater()
        return class_code

    def _output_ide_hints(self):
        hint_code = TextHolder()
        for c in self.options.classes.values():
            if c.name and self._should_output_class_generator(c):
                hint_code += self._generate_hint_for_class(c)
                hint_code += "\n"

        if self.options.caster_class:
            hint_code += self._generate_hint_for_class(self.options.caster_class)
            hint_code += "\n"

        for ms in self.options.functions.values():
            for m in ms:
                function_code = TextHolder()
                function_code += f"def {m.alias}(" + Indent()

                for arg in m.args:
                    function_code += Indent(
                        self.cpp_variable_to_py_with_hint(
                            arg, append=","
                        )
                    )

                function_code += f")->{self.cpp_type_to_python(m.ret_type)}:"
                function_code += "..." - IndentLater()

                hint_code += function_code
                hint_code += "\n"

        for v in self.options.variables.values():
            description = self.cpp_variable_to_py_with_hint(v)
            if description:
                hint_code += f"{description}"

        hint_code += "\n"
        hint_code += "\n"
        if self.options.constants_in_class:
            class_name = self.options.constants_in_class
            constants_class_code = TextHolder()
            constants_class_code += f"class {class_name}:" + Indent()
            for v in self.options.variables.values():
                description = self.cpp_variable_to_py_with_hint(v)
                if description:
                    constants_class_code += f"{description}"
            constants_class_code += "..." - IndentLater()

            hint_code += constants_class_code
            hint_code += "\n"

        for e in self.options.enums.values():
            enum_code = TextHolder()
            enum_code += f"pybind11::class {e.alias}(Enum):" + Indent()
            for v in e.values.values():
                description = self.cpp_variable_to_py_with_hint(v)
                enum_code += f"{description}"
            enum_code += "..." - IndentLater()

            hint_code += enum_code
            hint_code += "\n"

        # as all enums is exported, they becomes constants
        for e in self.options.enums.values():
            for v in e.values.values():
                description = self.cpp_variable_to_py_with_hint(v)
                if description:
                    hint_code += f"{description}"

        self._save_template(
            template_filename="hint.py.in",
            output_filename=f"{self.options.module_name}.pyi",
            hint_code=hint_code,
        )

    def _output_wrappers(self):
        pyclass_template = _read_file(f"{self.template_dir}/wrapper_class.h")
        wrappers = ""
        # generate callback wrappers
        for c in self.options.classes.values():
            if self._has_wrapper(c):
                wrapper_code = TextHolder()
                for ms in c.functions.values():
                    for m in ms:
                        # filter all arguments can convert as dict
                        dict_types = self._method_dict_types(m)
                        if m.is_virtual and not m.is_final:
                            function_code = self._generate_callback_wrapper(
                                m, dict_types=dict_types
                            )
                            wrapper_code += Indent(function_code)
                        if dict_types:
                            wrapper_code += self._generate_calling_wrapper(
                                c, m, dict_types=dict_types
                            )
                py_class_code = render_template(
                    pyclass_template, class_name=c.name, body=wrapper_code
                )
                wrappers += py_class_code
        self._save_template(f"wrappers.hpp", wrappers=wrappers)

    def _output_class_generator_declarations(self):
        class_generator_declarations = TextHolder()
        for c in self.options.classes.values():
            class_name = c.name
            if not self._should_wrap_as_dict(c):
                class_generator_function_name = self._generate_class_generator_function_name(
                    class_name
                )
                class_generator_declarations += f"void {class_generator_function_name}(pybind11::module &m);"

        self._save_template(
            f"class_generators.h",
            class_generator_declarations=class_generator_declarations,
        )

    def _should_output_class_generator(self, c: GeneratorClass):
        return not self._should_wrap_as_dict(c)

    def _output_module(self):

        call_to_generator_code, combined_class_generator_definitions = (
            self._output_class_definitions()
        )

        functions_code = TextHolder()
        functions_code += 1
        for name, ms in self.options.functions.items():
            has_overload = False
            if len(ms) > 1:
                has_overload = True
            for m in ms:
                functions_code += f"""m.def("{m.alias}",""" + Indent()
                functions_code += self.calling_wrapper(m, has_overload, append=',')
                functions_code += f"pybind11::call_guard<pybind11::gil_scoped_release>()"
                functions_code += f""");""" - Indent()

        constants_code = TextHolder()
        constants_code += 1
        for name, value in self.options.variables.items():
            pybind11_type = cpp_base_type_to_pybind11(value.type)
            literal = python_value_to_cpp_literal(value.default)
            if isinstance(value, GeneratorLiteralVariable):
                if value.literal_valid:
                    literal = value.literal
            constants_code += f"""m.add_object("{value.alias}", pybind11::{pybind11_type}({literal}));"""

        constants_class_code = TextHolder()
        constants_class_code += 1
        if self.options.constants_in_class:
            class_name = self.options.constants_in_class
            constants_class_code += f"""pybind11::class_<constants_class> c(m, "{class_name}");"""
            for name, value in self.options.variables.items():
                pybind11_type = cpp_base_type_to_pybind11(value.type)
                literal = python_value_to_cpp_literal(value.default)
                if isinstance(value, GeneratorLiteralVariable):
                    if value.literal_valid:
                        literal = value.literal
                constants_class_code += f"""c.attr("{value.alias}") = pybind11::{pybind11_type}({literal});"""

        enums_code = TextHolder()
        enums_code += 1
        for name, e in self.options.enums.items():
            if self.options.arithmetic_enum:
                arithmetic_enum_code = ", pybind11::arithmetic()"
            else:
                arithmetic_enum_code = ""
            enums_code += (
                f"""pybind11::enum_<{e.full_name}>(m, "{e.alias}"{arithmetic_enum_code})""" + Indent()
            )

            for v in e.values.values():
                enums_code += f""".value("{v.alias}", {e.full_name_of(v)})"""
            if self.options.export_enums:
                enums_code += ".export_values()"
            enums_code += ";" - Indent()

        casters_code = TextHolder()
        casters_code += 1
        if self.options.caster_class:
            c = self.options.caster_class
            casters_code += f"""auto c = autocxxpy::caster::bind(m, "{c.alias}"); """
            for ms in c.functions.values():
                for m in ms:
                    T = m.ret_type
                    if T:
                        casters_code += f"""c.def("{m.alias}", """ + Indent()
                        casters_code += f"""&autocxxpy::caster::copy<{m.ret_type}>"""
                        casters_code += ");" - IndentLater()

        self._save_template(
            "module.cpp",
            module_name=self.options.module_name,
            module_tag=self.module_tag,
            functions_code=functions_code,
            classes_code=call_to_generator_code,
            combined_class_generator_definitions=combined_class_generator_definitions,
            constants_code=constants_code,
            constants_class_code=constants_class_code,
            enums_code=enums_code,
            casters_code=casters_code,
        )

    def _output_class_definitions(self):
        class_template = _read_file(f"{self.template_dir}/class.cpp")
        call_to_generator_code = TextHolder()
        combined_class_generator_definitions = TextHolder()

        file_index = 1
        classes_in_this_file = 0

        # generate class call_to_generator_code
        class_generator_code = TextHolder()
        for c in self.options.classes.values():
            class_name = c.name
            if not class_name:
                continue
            if self._should_output_class_generator(c):
                # header first
                class_generator_function_name = self._generate_class_generator_function_name(
                    class_name
                )
                class_generator_code += f"void {class_generator_function_name}(pybind11::module &m)"
                class_generator_code += "{" + Indent()
                if self._has_wrapper(c):
                    wrapper_class_name = "Py" + c.name
                    if (
                        c.destructor is None or
                        c.destructor.access == "public"
                    ):
                        class_generator_code += f"""pybind11::class_<{c.name}, {wrapper_class_name}> c(m, "{class_name}");\n"""
                    else:
                        class_generator_code += f"pybind11::class_<" + Indent()
                        class_generator_code += f"{class_name},"
                        class_generator_code += f"std::unique_ptr<{class_name}, pybind11::nodelete>,"
                        class_generator_code += f"{wrapper_class_name}"
                        class_generator_code += (
                            f"""> c(m, "{class_name}");\n""" - Indent()
                        )
                else:
                    class_generator_code += f"""pybind11::class_<{class_name}> c(m, "{class_name}");\n"""

                # constructor
                if not c.is_pure_virtual:
                    if c.constructors:
                        for con in c.constructors:
                            arg_list = ",".join([arg.type for arg in con.args])
                            class_generator_code += (
                                f"""c.def(pybind11::init<{arg_list}>());\n"""
                            )
                    else:
                        class_generator_code += (
                            f"""c.def(pybind11::init<>());\n"""
                        )

                # functions
                for ms in c.functions.values():
                    has_overload: bool = False
                    if len(ms) > 1:
                        has_overload = True
                    for m in ms:
                        if m.is_static:
                            class_generator_code += (
                                f"""c.def_static("{m.alias}",""" + Indent()
                            )
                        else:
                            class_generator_code += (
                                f"""c.def("{m.alias}",""" + Indent()
                            )
                        class_generator_code += self.calling_wrapper(m, has_overload, append=',')
                        class_generator_code += f"pybind11::call_guard<pybind11::gil_scoped_release>()"
                        class_generator_code += f""");\n""" - Indent()

                # properties
                for name, value in c.variables.items():
                    class_generator_code += f"""c.AUTOCXXPY_DEF_PROPERTY({class_name}, "{value.alias}", {value.name});\n"""

                # post_register
                class_generator_code += f"AUTOCXXPY_POST_REGISTER_CLASS({class_name}, c);\n"

                class_generator_code += "}" - Indent()

                if self.options.split_in_files:
                    if self.options.max_classes_in_one_file <= 1:
                        self._save_file(
                            f"{class_name}.cpp",
                            self.render_template(
                                class_template,
                                class_generator_definition=class_generator_code,
                            ),
                        )
                        class_generator_code = TextHolder()
                    else:
                        classes_in_this_file += 1
                        if (
                            classes_in_this_file
                            >= self.options.max_classes_in_one_file
                        ):
                            self._save_file(
                                f"classes_{file_index}.cpp",
                                self.render_template(
                                    class_template,
                                    class_generator_definition=class_generator_code,
                                ),
                            )
                            file_index += 1
                            classes_in_this_file = 0
                            class_generator_code = TextHolder()

                else:
                    combined_class_generator_definitions += (
                        class_generator_code
                    )
                class_code = TextHolder()
                class_code += f"{class_generator_function_name}(m);"
                call_to_generator_code += Indent(class_code)

        if class_generator_code:
            self._save_file(
                f"classes_{file_index}.cpp",
                self.render_template(
                    class_template,
                    class_generator_definition=class_generator_code,
                ),
            )

        return call_to_generator_code, combined_class_generator_definitions

    @staticmethod
    def calling_wrapper(m, has_overload, append=''):
        code = TextHolder()
        code += f"""autocxxpy::calling_wrapper_v<"""
        if has_overload:
            code += f"""static_cast<{m.type}>(""" + Indent()
        code += f"""&{m.full_name}"""
        if has_overload:
            code += f""")""" - IndentLater()
        code += f""">{append}"""
        return code

    def _generate_class_generator_function_name(self, class_name):
        class_generator_function_name = f"generate_class_{class_name}"
        return class_generator_function_name

    def _has_wrapper(self, c: GeneratorClass):
        return not self._should_wrap_as_dict(c) and c.is_polymorphic

    def _method_dict_types(self, m):
        # filter all arguments can convert as dict
        arg_base_types = set(remove_cvref(i.type) for i in m.args)
        return set(
            i
            for i in (arg_base_types & self.options.dict_classes)
            if self._should_wrap_as_dict(i)
        )

    def _generate_callback_wrapper(
        self, m: GeneratorMethod, dict_types: set = None
    ):
        # calling_back_code
        ret_type = m.ret_type
        args = m.args
        arguments_signature = ",".join([f"{i.type} {i.name}" for i in args])
        arg_list = ",".join(
            ["this", f'"{m.alias}"', *[f"{i.name}" for i in args]]
        )

        if m.has_overload:
            cast_expression = f"static_cast<{m.type}>(&{m.full_name})"
        else:
            cast_expression = f"&{m.full_name}"

        function_code = TextHolder()
        function_code += (
            f"{ret_type} {m.name}({arguments_signature}) override\n"
        )
        function_code += "{\n" + Indent()
        function_code += (
            f"return autocxxpy::callback_wrapper<{cast_expression}>::call("
            + Indent()
        )
        function_code += f"{arg_list}" - IndentLater()
        function_code += f");"
        function_code += "}\n" - Indent()

        return function_code

    def _generate_calling_wrapper(self, c, m, dict_types: set = None):
        return ""
        pass

    def _save_template(
        self, template_filename: str, output_filename: str = None, **kwargs
    ):
        template = _read_file(f"{self.template_dir}/{template_filename}")
        if output_filename is None:
            output_filename = template_filename
        return self._save_file(
            output_filename, self.render_template(template, **kwargs)
        )

    def _save_file(self, filename, data):
        self.saved_files[filename] = data

    def render_template(self, templates, **kwargs):
        kwargs["includes"] = self._generate_includes()
        return render_template(templates, **kwargs)

    def _generate_includes(self):
        code = ""
        for i in self.options.includes:
            code += f"""#include "{i}"\n"""
        return code
