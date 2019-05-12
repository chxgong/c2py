import ast
import re

from setuptools import find_packages, setup

with open("autocxxpy/__init__.py", "rb") as f:
    version_line = re.search(
        r"__version__\s+=\s+(.*)", f.read().decode("utf-8")
    ).group(1)
    version = str(ast.literal_eval(version_line))

setup(
    name="autocxxpy",
    version=version,
    packages=find_packages(exclude=["tests.", ]),
    package_data={"": [
        "*.h",
        "*.hpp",
        "*.cpp",
        "*.c",
        "*.py.in",
        "*.dll",
    ]},
)
