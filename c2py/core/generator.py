import logging
import os
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Sequence

from c2py.core.core_types.generator_types import GeneratorNamespace, GeneratorSymbol, filter_symbols
from c2py.core.preprocessor import PreProcessorResult
from c2py.objects_manager import ObjectManager

logger = logging.getLogger(__file__)
mydir = os.path.split(os.path.abspath(__file__))[0]


def _read_file(name: str):
    with open(name, "rt") as f:
        return f.read()


def render_template(template: str, **kwargs):
    for key, replacement in kwargs.items():
        template = template.replace(f"${key}", str(replacement))
    return template


def mkdir(path: str):
    dir_path = os.path.dirname(path)
    if not os.path.exists(dir_path):
        mkdir(dir_path)
    os.mkdir(path)


def clear_dir(path: str):
    for root, dirs, files in os.walk(path):
        for d in dirs:
            clear_dir(os.path.join(path, d))
        for file in files:
            os.unlink(os.path.join(path, file))


@dataclass(repr=False)
class BasicGeneratorOption:
    module_name: str
    include_files: Sequence[str] = field(default_factory=list)
    pre_processor_result: PreProcessorResult = None


@dataclass(repr=False)
class GeneratorOptions(BasicGeneratorOption):
    g: GeneratorNamespace = None
    objects: ObjectManager = None

    @classmethod
    def from_preprocessor_result(
        cls,
        module_name: str,
        pre_processor_result: PreProcessorResult,
        include_files: Sequence[str] = None,
    ):
        c = cls(
            module_name=module_name,
            include_files=include_files,
            pre_processor_result=pre_processor_result,
            g=filter_symbols(pre_processor_result.g,
                             GeneratorOptions._should_generate_symbol
                             ),
            objects=pre_processor_result.objects,
        )
        return c

    @staticmethod
    def _should_generate_symbol(s: GeneratorSymbol):
        return s.generate and s.name


@dataclass()
class GeneratorResult:
    saved_files: Dict[str, str] = None

    def output(self, output_dir: str, clear: bool = False):
        # clear output dir
        if not os.path.exists(output_dir):
            os.mkdir(output_dir)
        if clear:
            clear_dir(output_dir)

        for name, data in self.saved_files.items():
            output_filepath = f"{output_dir}/{name}"
            dir_path = os.path.dirname(output_filepath)
            if not os.path.exists(dir_path):
                mkdir(dir_path)
            with open(output_filepath, "wt") as f:
                f.write(data)

    def print_filenames(self):
        print(f"# of files generated : {len(self.saved_files)}")
        for name in self.saved_files:
            print(name)


class GeneratorBase:
    """

    """
    template_dir = os.path.join(mydir, "../", "templates")

    def __init__(self, options: BasicGeneratorOption):
        self.options = options
        self.saved_files: Dict[str, str] = {}

    @abstractmethod
    def _process(self):
        """
        save anything you generated into self.saved_files.
        you can use self._save_template() or self._save_file() to save files into self.saved_files.
        """

    def generate(self):
        self._process()
        return GeneratorResult(self.saved_files)

    @property
    def module_name(self):
        return self.options.module_name

    @property
    def module_tag(self):
        return 'tag_' + self.options.module_name

    @property
    def module_class(self):
        return "module_" + self.options.module_name

    def _save_template(
        self, template_filename: str, output_filename: str = None, **kwargs
    ):
        template_content = self._template_content(template_filename)
        if output_filename is None:
            output_filename = template_filename
        code = self._render_template(template_content, **kwargs)
        return self._save_file(
            output_filename, code
        )

    def _template_content(self, template_filename):
        content = _read_file(f"{self.template_dir}/{template_filename}")
        return content

    def _render_file(self, template_filename: str, **kwargs):
        template_content = self._template_content(template_filename)
        return self._render_template(template_content, **kwargs)

    def _save_file(self, filename: str, data: str):
        self.saved_files[filename] = data

    def _render_template(self, templates: str, **kwargs):
        kwargs["includes"] = self._generate_includes()
        kwargs["module_name"] = self.module_name
        kwargs["module_tag"] = self.module_tag
        kwargs["module_class"] = self.module_class
        return render_template(templates, **kwargs)

    def _generate_includes(self):
        code = ""
        for i in self.options.include_files:
            code += f"""#include "{i}"\n"""
        return code
